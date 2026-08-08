import { test } from 'node:test';
import assert from 'node:assert';
import {
  jstDateKey,
  jstDateLabel,
  findDueCheckpoint,
  stripMarkdown,
  safeSlice,
  scheduleFollowUps,
  assertValidPostText,
  nextTriviaArticle,
  SLOT_PROFILES,
  isTransientPostError,
  TRIVIA_QUIET_HOURS_UNTIL,
  fixKnownMisspellings,
  pickDueSlot,
  parsePollQuiz,
  detectStockShift,
  SLOT_QUIET_HOURS_UNTIL,
  DEFAULT_RELEASE_MIN,
  releaseMinOf,
  slotReleaseOrderOk,
  TRIVIA_LOW_STOCK,
  searchPlanFor,
  formatSearchResults,
  researchLine,
  todaysPostDigest,
} from '../post-quiz.mjs';

// JSTの特定時刻のepoch msを作るヘルパー（基準日: 2026-07-21・火曜日）
function jstTime(hh, mm, day = 21) {
  return Date.UTC(2026, 6, day, hh - 9, mm, 0);
}

test('jstDateLabel: 正しい日付・曜日ラベルを返す', () => {
  // 実際に事故が起きた時刻（2026-07-21 05:17 JST、本来は火曜日）
  assert.strictEqual(jstDateLabel(jstTime(5, 17)), '2026年7月21日火曜日');
});

test('jstDateKey: JSTの日付キー(YYYY-MM-DD)を返す', () => {
  assert.strictEqual(jstDateKey(jstTime(5, 17)), '2026-07-21');
  // JST 0:30は前日UTCの15:30。日付境界をまたいでも正しくJST日付になること
  assert.strictEqual(jstDateKey(jstTime(0, 30)), '2026-07-21');
});

test('stripMarkdown: **太字**を平文に変換する（実際のバグの再現）', () => {
  const r = stripMarkdown('**Q1. 米軍とイランが再び交戦。最新の状況は？**\nA: 精密攻撃を実施。');
  assert.ok(!r.includes('**'));
  assert.ok(r.startsWith('Q1. 米軍とイランが再び交戦'));
});

test('stripMarkdown: 独立行の"---"を罫線文字に変換する', () => {
  const r = stripMarkdown('あいさつ文\n\n---\n\nQ1. 本文');
  assert.ok(!r.includes('---'));
  assert.ok(r.includes('─'.repeat(21)));
});

test('stripMarkdown: URL中のハイフンなど独立行でないものは変換しない', () => {
  const r = stripMarkdown('詳しくは https://example.com/a--b--c を参照');
  assert.strictEqual(r, '詳しくは https://example.com/a--b--c を参照');
});

test('safeSlice: 絵文字の直前で切れるケースを安全に処理する（実際の事故の再現）', () => {
  // 39文字 + 🐹（サロゲートペア）= 41コード単位。素のslice(0,40)だと孤立サロゲートが残る
  const text = 'あ'.repeat(39) + '🐹';
  const fixed = safeSlice(text, 40);
  assert.strictEqual(fixed, 'あ'.repeat(39)); // 絵文字ごと落として孤立サロゲートを作らない
});

test('safeSlice: サロゲート境界に関係ない通常ケースは従来通り', () => {
  const text = 'あいうえお'.repeat(20);
  assert.strictEqual(safeSlice(text, 40), text.slice(0, 40));
});

test('safeSlice: maxLenより短い文字列はそのまま返す', () => {
  const text = 'あいうえお🐹';
  assert.strictEqual(safeSlice(text, 100), text);
});

test('assertValidPostText: 孤立サロゲートを含む文字列は例外を投げる', () => {
  const bad = 'あ'.repeat(39) + '\ud83d'; // 高サロゲート単体
  assert.throws(() => assertValidPostText(bad, jstTime(5, 17)), /孤立サロゲート/);
});

test('assertValidPostText: 正常な文字列（絵文字含む）はエラーにならない', () => {
  assert.doesNotThrow(() => assertValidPostText('おはようございます🐹 今日もいい天気', jstTime(5, 17)));
});

test('assertValidPostText: 実際の日付と食い違う曜日表記は例外を投げる（実際の事故の再現）', () => {
  // 2026-07-21は火曜日なのに「月曜日です」と書かれているケース
  const bad = '今朝の通勤ブリーフィング、月曜日です。週明け早々……';
  assert.throws(() => assertValidPostText(bad, jstTime(5, 17)), /曜日表記/);
});

test('assertValidPostText: 実際の日付と一致する曜日表記は許可される', () => {
  const ok = '今朝の通勤ブリーフィング、火曜日です。';
  assert.doesNotThrow(() => assertValidPostText(ok, jstTime(5, 17)));
});

test('assertValidPostText: 曜日への言及が無い文章はチェック対象外', () => {
  assert.doesNotThrow(() => assertValidPostText('速報：中東情勢が緊迫化しています', jstTime(5, 17)));
});

test('assertValidPostText: 本文途中の別日付への曜日言及は誤検知しない（未来の予定への正当な言及）', () => {
  // 冒頭は今日(火曜日)の話題で始まり、本文の途中（先頭80文字より後）で別の日
  // （決勝は来週日曜日）に触れるケース。これは正当な内容なのでエラーにしてはいけない
  const text = '火曜日の朝です。'.padEnd(100, '　') + 'なお決勝は来週の日曜日に開催されます。';
  assert.doesNotThrow(() => assertValidPostText(text, jstTime(5, 17)));
});

test('findDueCheckpoint: ちょうどの時刻でヒットする', () => {
  const cp = findDueCheckpoint(jstTime(9, 30), []);
  assert.strictEqual(cp.hm, '09:30');
  assert.strictEqual(cp.fallback, 'quiz');
});

test('findDueCheckpoint: 猶予時間内（cron遅延を想定した20分後）でもヒットする', () => {
  const cp = findDueCheckpoint(jstTime(9, 50), []);
  assert.strictEqual(cp.hm, '09:30');
});

test('findDueCheckpoint: 猶予切れの古いチェックポイントは飛ばして次にヒットする', () => {
  const cp = findDueCheckpoint(jstTime(10, 20), []);
  assert.strictEqual(cp.hm, '10:00');
});

test('findDueCheckpoint: 深夜2:00/4:00はforceArticle=trueでヒットする', () => {
  assert.strictEqual(findDueCheckpoint(jstTime(2, 5), []).forceArticle, true);
  assert.strictEqual(findDueCheckpoint(jstTime(4, 0), []).forceArticle, true);
});

test('findDueCheckpoint: 処理済み(doneKeys)のチェックポイントは再ヒットしない', () => {
  const todayKey = jstDateKey(jstTime(9, 30));
  const cp = findDueCheckpoint(jstTime(9, 40), [`${todayKey}_09:30`]);
  assert.strictEqual(cp, null);
});

test('findDueCheckpoint: どのチェックポイントにも該当しない時刻はnull', () => {
  assert.strictEqual(findDueCheckpoint(jstTime(20, 0), []), null);
});

test('scheduleFollowUps: followUp=falseなら何も積まない', () => {
  const state = {};
  scheduleFollowUps(state, 'h', 't', 1000, false);
  assert.strictEqual(state.breakingFollowUps, undefined);
});

test('scheduleFollowUps: followUp=trueなら常に30分後の1件のみ積む', () => {
  const state = {};
  const now = 1_000_000;
  scheduleFollowUps(state, 'h', 't', now, true);
  assert.strictEqual(state.breakingFollowUps.length, 1);
  assert.strictEqual(state.breakingFollowUps[0].dueAt, now + 30 * 60000);
  assert.strictEqual(state.breakingFollowUps[0].stageLabel, '30分後');
});

test('nextTriviaArticle: 未投稿分の先頭を返す', () => {
  const stock = ['1本目', '2本目', '3本目'];
  assert.strictEqual(nextTriviaArticle(stock, 0), '1本目');
  assert.strictEqual(nextTriviaArticle(stock, 2), '3本目');
});

test('nextTriviaArticle: ストックが尽きたらnullを返す', () => {
  const stock = ['1本目'];
  assert.strictEqual(nextTriviaArticle(stock, 1), null);
  assert.strictEqual(nextTriviaArticle([], 0), null);
});

test('assertValidPostText: checkWeekday=falseなら曜日の不一致を許可する（豆知識の永続ネタ用）', () => {
  // 「月曜日の語源」のような永続ネタは、実際の曜日と無関係に曜日表記を含む
  const article = '「月曜日」の月は、天体の月のことです。曜日の名前は七曜に由来するとされています。';
  assert.throws(() => assertValidPostText(article, jstTime(5, 17)), /曜日表記/); // 既定では従来どおり弾く
  assert.doesNotThrow(() => assertValidPostText(article, jstTime(5, 17), { checkWeekday: false }));
});

test('assertValidPostText: checkWeekday=falseでも孤立サロゲートは必ず弾く', () => {
  const bad = 'あ'.repeat(39) + '\ud83d';
  assert.throws(() => assertValidPostText(bad, jstTime(5, 17), { checkWeekday: false }), /孤立サロゲート/);
});

test('isTransientPostError: 5xxは一時的、4xxとバリデーション違反は恒久的と判定する', () => {
  assert.strictEqual(isTransientPostError(new Error('HTTP 503: {}')), true);
  assert.strictEqual(isTransientPostError(new Error('HTTP 500: {}')), true);
  // 重複投稿の拒否など、その記事固有で何度試しても直らないもの
  assert.strictEqual(isTransientPostError(new Error('HTTP 403: duplicate content')), false);
  assert.strictEqual(isTransientPostError(new Error('投稿本文に不正な文字（孤立サロゲート）が含まれています（位置39）')), false);
  assert.strictEqual(isTransientPostError(undefined), false);
});

test('fixKnownMisspellings: 「高島首相」などの誤記を高市に直す（実際の事故の再現）', () => {
  assert.strictEqual(fixKnownMisspellings('高島首相が所信表明'), '高市首相が所信表明');
  assert.strictEqual(fixKnownMisspellings('高島総理'), '高市総理');
  assert.strictEqual(fixKnownMisspellings('高島内閣の支持率'), '高市内閣の支持率');
  assert.strictEqual(fixKnownMisspellings('高島政権'), '高市政権');
  // 1つの本文に複数回出てもすべて直す
  assert.strictEqual(fixKnownMisspellings('高島首相は…。高島内閣は…'), '高市首相は…。高市内閣は…');
});

test('fixKnownMisspellings: 役職を伴わない「高島」姓は書き換えない（実在の別人を壊さない）', () => {
  assert.strictEqual(fixKnownMisspellings('高島屋で買い物'), '高島屋で買い物');
  assert.strictEqual(fixKnownMisspellings('高島さんが受賞'), '高島さんが受賞');
  assert.strictEqual(fixKnownMisspellings('高島平駅'), '高島平駅');
});

test('fixKnownMisspellings: 正しい表記や無関係な本文はそのまま返す', () => {
  assert.strictEqual(fixKnownMisspellings('高市首相が所信表明'), '高市首相が所信表明');
  assert.strictEqual(fixKnownMisspellings('今日は良い天気です🐹'), '今日は良い天気です🐹');
});

// 2026-07-30の事故: 4時台の豆知識が4:59に投稿された結果、投稿間隔(30分)の制限で5時台の
// 朝ブリーフィングが見送られ、次の実行(6:34)では直近スロットが6時台に移っていて永久に消えた
test('pickDueSlot: 前のスロットが未投稿なら取り戻す（朝ブリーフィングが消えた事故の再現）', () => {
  const t459 = jstTime(4, 59, 30);            // 4時台の豆知識を4:59に投稿
  const at634 = jstTime(6, 34, 30);           // 次の実行は6:34（5時台は過ぎている）
  const picked = pickDueSlot(at634, t459);
  assert.strictEqual(jstDateLabel(picked).includes('7月30日'), true);
  assert.strictEqual(new Date(picked + 9 * 3600000).getUTCHours(), 5, '5時台のブリーフィングを選ぶべき');
});

test('pickDueSlot: 前のスロットが投稿済みなら現在のスロットを選ぶ', () => {
  const posted5 = jstTime(5, 50, 30);         // 5時台のブリーフィングは投稿済み
  const at647 = jstTime(6, 47, 30);           // 6時台の解禁(6:45)後
  assert.strictEqual(new Date(pickDueSlot(at647, posted5) + 9 * 3600000).getUTCHours(), 6);
});

// ===== スロットの解禁時刻（番組表を保ったまま実行機会だけ増やすための仕組み） =====

test('解禁時刻はスロット順に単調増加している（latestSlotEpochの前提）', () => {
  assert.ok(slotReleaseOrderOk(), '解禁時刻の順序がスロット順と食い違っています');
});

test('releaseMinOf: 既定は45分、12時台だけ13分', () => {
  assert.strictEqual(releaseMinOf(5), DEFAULT_RELEASE_MIN);
  assert.strictEqual(releaseMinOf(6), 45);
  assert.strictEqual(releaseMinOf(12), 13, '昼のクイズは12:13に出す運用');
});

test('pickDueSlot: 解禁前の時台は選ばれない（投稿時刻が:02〜:47でばらつかない）', () => {
  const posted5 = jstTime(5, 50, 30);
  // 6:34は6時台に入っているが解禁(6:45)前。15分おきに起動しても6時台はまだ出さない
  assert.strictEqual(new Date(pickDueSlot(jstTime(6, 34, 30), posted5) + 9 * 3600000).getUTCHours(), 5);
  // 6:47は解禁後なので6時台に進む
  assert.strictEqual(new Date(pickDueSlot(jstTime(6, 47, 30), posted5) + 9 * 3600000).getUTCHours(), 6);
});

// 2026-08-05の実測: 毎時47分の1本だけでは約半数のcronが間引かれ、9スロット中6本しか投稿できていなかった。
// 解禁を:45にしたうえで :02/:17/:32/:47 に起動することで、1スロットにつき4回の機会を確保する
test('pickDueSlot: :47の起動が間引かれても次の時台の:02/:17/:32で取り戻せる', () => {
  const posted5 = jstTime(5, 50, 30);         // 5時台まで投稿済み
  for (const [hh, mm] of [[7, 2], [7, 17], [7, 32]]) {
    const picked = new Date(pickDueSlot(jstTime(hh, mm, 30), posted5) + 9 * 3600000).getUTCHours();
    assert.strictEqual(picked, 6, `${hh}:${mm}では6時台の豆知識を取り戻すべき`);
  }
  // 7:47（7時台の解禁後）でも、未投稿の6時台が期限内なら既存のキャッチアップが優先して取り戻す。
  // 6時台も7時台も豆知識なので、どちらを出しても投稿は1本で同じ。取りこぼしを作らない側に倒す
  assert.strictEqual(new Date(pickDueSlot(jstTime(7, 47, 30), posted5) + 9 * 3600000).getUTCHours(), 6);
});

test('pickDueSlot: 投稿直後に再度起動しても同じスロットを二重に選ばない', () => {
  const posted6 = jstTime(6, 47, 30);         // 6時台を投稿した直後
  const slot = pickDueSlot(jstTime(7, 2, 30), posted6);
  // スロット自体は6時台のままだが、lastPostedAtがそれ以降なので呼び出し側で未投稿判定にならない
  assert.strictEqual(new Date(slot + 9 * 3600000).getUTCHours(), 6);
  assert.ok(posted6 >= slot, '投稿済み判定(lastPostedAt < slotEpoch)が成立してはいけない');
});

test('豆知識の在庫警告しきい値は1日の消費本数より多い', () => {
  const triviaPerDay = Object.values(SLOT_PROFILES).filter(p => p.kind === 'trivia').length;
  assert.ok(TRIVIA_LOW_STOCK > triviaPerDay,
    `しきい値(${TRIVIA_LOW_STOCK}本)が1日の消費(${triviaPerDay}本)以下だと、気づいた時には当日中に尽きます`);
});

test('pickDueSlot: 未投稿の豆知識が本命コンテンツを押しのけない', () => {
  // 4時台の豆知識が未投稿のまま5時台に入った場合、豆知識ではなくブリーフィングを優先する
  const postedYesterday = jstTime(20, 30, 29);
  const at547 = jstTime(5, 47, 30);
  assert.strictEqual(new Date(pickDueSlot(at547, postedYesterday) + 9 * 3600000).getUTCHours(), 5);
});

test('pickDueSlot: 期限(既定6時間)を超えた前のスロットは取り戻さない', () => {
  const t459 = jstTime(4, 59, 30);
  const at1547 = jstTime(15, 47, 30);         // 5時台から10時間以上経過
  assert.notStrictEqual(new Date(pickDueSlot(at1547, t459) + 9 * 3600000).getUTCHours(), 5);
});

// 2026-07-20/23/31に3回起きた事故: 記事タイトル中のダブルクォートでJSONが壊れた。
// 区切り記号方式なら、本文にどんな記号が入っても解析できる
test('parsePollQuiz: ダブルクォートを含んでも全項目を取り出せる（実際の事故の再現）', () => {
  const raw = [
    '---POST-START---',
    '放送中の「風、薫る」で佐野晶哉が演じる"シマケン"。彼の職業はどっち？',
    '---POST-END---',
    '---ANSWER-START---',
    '正解は「活字工」でした！',
    '',
    '🌰豆知識: "文選工"とも呼ばれました。',
    '---ANSWER-END---',
    'choices: 活字工（新聞社勤務） | 印刷工（印刷所勤務）',
    'source: クランクイン！「"りん"見上愛、"シマケン"佐野晶哉と再会」',
    'sourceUrl: https://example.com/a',
    'category: エンタメ・二択',
  ].join('\n');
  const q = parsePollQuiz(raw);
  assert.ok(q.question.includes('"シマケン"'));
  assert.deepStrictEqual(q.choices, ['活字工（新聞社勤務）', '印刷工（印刷所勤務）']);
  assert.ok(q.answer.includes('\n'), '正解文は複数行でも欠けない');
  assert.ok(q.source.includes('"りん"'));
  assert.strictEqual(q.sourceUrl, 'https://example.com/a');
  assert.strictEqual(q.category, 'エンタメ・二択');
});

test('parsePollQuiz: 本文の区切りが無ければ例外を投げる', () => {
  assert.throws(() => parsePollQuiz('choices: A | B'), /区切りが見つかりません/);
});

test('detectStockShift: 末尾追加だけなら異常を検知しない', () => {
  const stock = ['1本目の記事', '2本目の記事', '3本目の記事'];
  assert.strictEqual(detectStockShift(stock, 2, '2本目の記事'), null);
});

test('detectStockShift: 途中に挿入されて位置がずれたら検知する', () => {
  const stock = ['割り込み記事', '1本目の記事', '2本目の記事'];
  const r = detectStockShift(stock, 2, '2本目の記事');   // idx2の1つ前は「1本目」になってしまっている
  assert.ok(r, 'ずれを検知すべき');
  assert.strictEqual(r.foundAt, 2);
});

test('detectStockShift: 投稿済みの記事が削除されたら見つからないと報告する', () => {
  const stock = ['別の記事A', '別の記事B'];
  const r = detectStockShift(stock, 2, '消えた記事');
  assert.ok(r);
  assert.strictEqual(r.foundAt, -1);
});

test('detectStockShift: 初回（まだ1本も投稿していない）は検知対象外', () => {
  assert.strictEqual(detectStockShift(['a'], 0, undefined), null);
});

test('深夜ガード: スロット全体は5時前、豆知識はさらに厳しく6時前を止める', () => {
  assert.strictEqual(SLOT_QUIET_HOURS_UNTIL, 5);
  assert.ok(TRIVIA_QUIET_HOURS_UNTIL >= SLOT_QUIET_HOURS_UNTIL,
    '豆知識のガードがスロット全体より緩いと、深夜に豆知識だけ出てしまう');
});

test('SLOT_PROFILES: 豆知識は1日5枠（6/7/8/10/15時台）', () => {
  const triviaHours = Object.entries(SLOT_PROFILES)
    .filter(([, p]) => p.kind === 'trivia')
    .map(([h]) => Number(h))
    .sort((a, b) => a - b);
  assert.deepStrictEqual(triviaHours, [6, 7, 8, 10, 15]);
});

test('SLOT_PROFILES: 最も早い豆知識スロットが深夜ガードで塞がれていない', () => {
  // TRIVIA_QUIET_HOURS_UNTIL より前の時台に豆知識スロットを置くと、その枠は永久に投稿されない
  const earliestTrivia = Math.min(...Object.entries(SLOT_PROFILES)
    .filter(([, p]) => p.kind === 'trivia').map(([h]) => Number(h)));
  assert.ok(earliestTrivia >= TRIVIA_QUIET_HOURS_UNTIL,
    `最早の豆知識スロット(${earliestTrivia}時)が深夜ガード(${TRIVIA_QUIET_HOURS_UNTIL}時)より前です`);
});

test('SLOT_PROFILES: スロットは1時間以上離れている（投稿間隔30分の下限に抵触しない）', () => {
  const hours = Object.keys(SLOT_PROFILES).map(Number).sort((a, b) => a - b);
  for (let i = 1; i < hours.length; i++) {
    assert.ok(hours[i] - hours[i - 1] >= 1, `${hours[i - 1]}時と${hours[i]}時が近すぎます`);
  }
});

// ===== 自前検索（Anthropicのweb_searchツールの代替・コスト削減） =====

test('searchPlanFor: コンテンツ種別ごとに固定クエリを返す', () => {
  assert.ok(searchPlanFor('briefing').queries.length >= 2);
  assert.strictEqual(searchPlanFor('briefing').days, 1, 'ニュース用途なので当日分に絞る');
  assert.ok(searchPlanFor('quiz', { genre: 'スポーツの話題' }).queries[0].includes('スポーツ'));
  // 未知の種別でも落ちずに既定のプランへ倒す（新しいスロットを足した時に無言で壊れないように）
  assert.ok(searchPlanFor('unknown-kind').queries.length > 0);
});

test('searchPlanFor: 話題が空のfeature/followUpはプランを作らない（空クエリで検索しない）', () => {
  assert.strictEqual(searchPlanFor('feature', { topic: '' }), null);
});

test('formatSearchResults: URLの重複を除き、上位2件だけ全文を載せる', () => {
  const results = [
    { title: 'A', url: 'https://x/1', content: '短い要約A', raw_content: 'A'.repeat(9000), published_date: '2026-08-06' },
    { title: 'B', url: 'https://x/2', content: '短い要約B', raw_content: 'B'.repeat(9000) },
    { title: 'C', url: 'https://x/3', content: '短い要約C', raw_content: 'C'.repeat(9000) },
    { title: 'Aの重複', url: 'https://x/1', content: '同じ記事', raw_content: 'D'.repeat(9000) },
  ];
  const out = formatSearchResults(results);
  assert.strictEqual((out.match(/https:\/\/x\/1/g) || []).length, 1, '同じURLは1回だけ');
  assert.ok(out.includes('A'.repeat(3000)), '1件目は全文が載る');
  assert.ok(!out.includes('C'.repeat(3000)), '3件目以降はスニペットのみ');
  assert.ok(out.includes('短い要約C'));
  assert.ok(out.includes('日時: 2026-08-06'));
});

test('formatSearchResults: 総量の上限を超えない（入力トークンの上振れを防ぐ）', () => {
  const many = Array.from({ length: 60 }, (_, i) => ({
    title: `記事${i}`, url: `https://x/${i}`, content: 'あ'.repeat(2000),
  }));
  assert.ok(formatSearchResults(many, 24000).length <= 24000);
});

test('formatSearchResults: URLの無い結果は捨てる（出典URLに使えないため）', () => {
  assert.strictEqual(formatSearchResults([{ title: 'URLなし', content: '本文' }]), '');
});

// プロンプトが「検索して」と指示しているのに検索結果が添付されていない、という食い違いは
// モデルが情報源なしで書く（＝作り話をする）事故に直結するため、モードと文面を必ず連動させる
test('researchLine: モードによって情報源の指示が切り替わる', () => {
  assert.ok(researchLine('self', '「今日のニュース」').includes('【検索結果】'));
  assert.ok(!researchLine('self', '「今日のニュース」').includes('Web検索を使って'));
  assert.ok(researchLine('tool', '「今日のニュース」').includes('Web検索を使って'));
  assert.ok(researchLine('tool', '「今日のニュース」', '国内外から').includes('国内外から'));
});

// 2026-08-08、10時のクイズで「甲子園は8月5日開幕」と正しく投稿した同じ日の20時の振り返りが
// 「8月8日が開幕日」と誤って出題し、訂正を出す事故が起きた。同じ日の自分の投稿を
// 生成時に読ませることで、この種の自己矛盾を防ぐ
test('todaysPostDigest: 当日の投稿だけを古い順に並べる', () => {
  const jst = (h, m) => Date.parse(`2026-08-08T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00+09:00`);
  const now = jst(20, 56);
  const history = [ // postHistoryは新しい順に積まれる
    { postedAt: jst(20, 56), kind: 'recap', category: '夜の振り返り', textPreview: '熊本の避難所に6630人' },
    { postedAt: jst(10, 6), kind: 'quiz', category: 'スポーツ', textPreview: '第108回全国高校野球選手権大会が8月5日に開幕しました' },
    { postedAt: Date.parse('2026-08-07T21:29:00+09:00'), kind: 'recap', category: '夜の振り返り', textPreview: '前日の振り返り' },
  ];
  const out = todaysPostDigest(history, now);
  const lines = out.split('\n');
  assert.strictEqual(lines.length, 2, '前日の投稿は含めない');
  assert.ok(lines[0].startsWith('- 10:06 [スポーツ]'), `古い順に並ぶ: ${lines[0]}`);
  assert.ok(lines[0].includes('8月5日に開幕'), '本文の冒頭が読める');
  assert.ok(lines[1].startsWith('- 20:56 [夜の振り返り]'));
  assert.ok(!out.includes('前日の振り返り'));
});

test('todaysPostDigest: 改行を1行に潰す（プロンプトの箇条書きが崩れない）', () => {
  const now = Date.parse('2026-08-08T20:56:00+09:00');
  const out = todaysPostDigest([{ postedAt: now, kind: 'quiz', textPreview: '1行目\n\n2行目' }], now);
  assert.strictEqual(out.split('\n').length, 1);
  assert.ok(out.includes('1行目 2行目'));
});

test('todaysPostDigest: 履歴が空・当日分なしなら空文字（プロンプトに何も足さない）', () => {
  assert.strictEqual(todaysPostDigest([], Date.now()), '');
  assert.strictEqual(todaysPostDigest(undefined, Date.now()), '');
  assert.strictEqual(
    todaysPostDigest([{ postedAt: Date.parse('2026-08-07T10:00:00+09:00'), kind: 'quiz', textPreview: 'x' }],
      Date.parse('2026-08-08T20:56:00+09:00')),
    '');
});

test('todaysPostDigest: categoryが空ならkindで代用する', () => {
  const now = Date.parse('2026-08-08T20:56:00+09:00');
  assert.ok(todaysPostDigest([{ postedAt: now, kind: 'trivia', category: '', textPreview: 'x' }], now).includes('[trivia]'));
});
