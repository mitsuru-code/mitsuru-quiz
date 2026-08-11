// ============================================================
// 豆知識の執筆素材を配信する（人が書いて、人が投稿するための下ごしらえ）
//
// なぜこれが必要か:
//   Xの Original Content Rewards Program は、対象外の条件として
//   「created **or** posted using automated means」を挙げている。orなので、
//   生成が自動でも投稿が自動でも失格になる。cloud-bot（自動投稿）の投稿は
//   人が手書きした豆知識記事であっても "posted" 側で落ちる。
//   適格にするには「人が書く」「人が公式Xアプリから投稿する」の両方が要る。
//
// 一方、調査・素材集めは著作行為ではないので制約の外にある（新聞のスクラップと同じ）。
// 線引きは"文章表現"にある。そこでこのスクリプトは
//   テーマを出す → 裏を取る → 事実の箇条書きだけを配る
// までを担当し、文章を書く仕事には一切踏み込まない。
//
// 【重要】出力は意図的に「そのまま投稿できない形」にしてある。
//   完成文・見出しコピー・絵文字・「朝礼で使うなら」の台本を禁止し、
//   体言止めのデータ列挙だけを出させている。AIの書いた文をコピペしたり
//   少し直して出したりすると "reposted with only minor edits" 条項で失格になるため、
//   構造的にコピペできないようにするのが最大の安全策になる。
//   プロンプトを緩めて「読みやすい文章」にしたくなったら、この規約要件を思い出すこと。
//
// 記事そのものの書き方（3部構成・事実確度・禁止話題）は cloud-bot/trivia-style.md が正本。
// このスクリプトはそこに書かれた「取材」の部分だけを肩代わりする。
// ============================================================
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { research, callAnthropic, jstDateLabel, jstDateKey, safeSlice } from './post-quiz.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TRIVIA_STOCK_FILE = path.join(__dirname, 'trivia-stock.json');

// 1回の配信で出すテーマ候補の数。人が1日に書ける本数（2〜3本）より少し多めにして選ぶ余地を残す
export const TOPICS_PER_SHEET = 3;

// 既出テーマの一覧。trivia-style.md が「配列の全件の1行目に目を通し、同じ主題を出さないこと」と
// 定めているので、その1行目だけを機械的に集めて重複回避の材料にする。
// 投稿済み・未投稿を区別しないのは、未投稿分も「いずれ出るネタ」で重複には違いないため
export function loadCoveredTopics(stockPath = TRIVIA_STOCK_FILE) {
  let stock;
  try {
    stock = JSON.parse(fs.readFileSync(stockPath, 'utf8'));
  } catch {
    return [];
  }
  if (!Array.isArray(stock)) return [];
  return stock
    .map(a => String(a || '').split('\n')[0].trim())
    .filter(Boolean);
}

// テーマ出しのプロンプト。ここでは事実を書かせない（モデルの記憶は当てにしない）。
// 何を調べるかだけ決めさせて、裏取りは次の検索フェーズに回す
export function buildTopicPrompt(covered, count = TOPICS_PER_SHEET) {
  return `あなたは朝礼ネタの企画担当です。日本語の「豆知識」記事のテーマ候補を${count}件出してください。

【読者】
朝の通勤中に読んで、その日の朝礼でそのまま話す人（課長クラス）。
「知らなかった」と「言われてみれば確かに」が両方あるネタが喜ばれます。

【ジャンル】
食・生活／科学・自然／歴史・言葉の由来／仕事・数字の見方 など。${count}件は別々の分野に散らしてください。

【既に扱ったテーマ（重複禁止）】
切り口を変えただけの同じ話も重複とみなします。以下と主題が重ならないものを出してください。
${covered.map(t => `- ${t}`).join('\n')}

【避けるテーマ】
- 政治・宗教・思想信条
- 実在の個人・企業への論評
- 健康効能（「〜が治る」「〜に効く」）。薬機法上のリスクがあるため話題ごと避ける
- 事故・災害・病気を茶化すもの
- 速報ニュースに依存するもの（恒久的に成り立つネタだけ）
- 出典の言えない統計や「日本初」「世界一」に頼るもの

【出力形式】厳守
${count}行だけ出力してください。番号も記号も説明も前置きも付けないでください。
1行につき「テーマ / 調べるべきこと」の形式で、全角スラッシュではなく半角スラッシュで区切ってください。

例:
コーヒーの脱カフェイン製法 / カフェインだけを抜く仕組みと、水を使う製法の原理`;
}

// モデルの返答からテーマ行を取り出す。番号や記号を付けてくることがあるので寛容に剥がす
export function parseTopics(text, count = TOPICS_PER_SHEET) {
  return String(text || '')
    .split('\n')
    .map(l => l.replace(/^\s*(?:[-*•]|\d+[.)、]|【\d+】)\s*/, '').trim())
    .filter(l => l.includes('/') && l.length > 5)
    .slice(0, count);
}

export function topicPlanFor(topics) {
  const queries = topics.map(t => safeSlice(t.split('/')[0].trim(), 60)).filter(Boolean);
  // topic:'general' で恒久ネタの解説ページを引く（'news'だと当日の記事しか返らず、
  // 「なぜそうなるのか」を書いた定説の解説が落ちる）
  return queries.length ? { kind: 'trivia-material', queries, topic: 'general' } : null;
}

// 素材メモ本体のプロンプト。検索結果から事実だけを抜き出させる
export function buildFactPrompt(topics, dateLabel, researchContext) {
  return `今日は${dateLabel}です。あなたはライターのために事実を集める調査アシスタントです。
以下のテーマについて、人間が「豆知識」記事を書くための素材メモを作ってください。

【テーマ】
${topics.map((t, i) => `${i + 1}. ${t}`).join('\n')}

【あなたの仕事ではないこと】
あなたは記事を書きません。書くのは人間です。あなたは材料を並べるだけです。

【絶対的な禁止事項】
- 完成した文章を書かない。「です」「ます」「でした」で終わる文を1つも書かない
- 記事本文・見出しコピー・「朝礼で使うなら」の台本を書かない
- 感想・評価・意見・オチ・教訓を書かない（起きている事実と仕組みだけ）
- 絵文字を使わない

【書き方】
すべて体言止めの箇条書きにしてください。データの列挙であって、読み物にしないこと。

【出力形式】厳守
テーマごとに以下の形式だけで出力してください。前置きも締めalso書かないでください。

## 1. （テーマ名。体言止め10〜25字）
- 事実: （何がそうなっているか。体言止めで2〜3項目）
- 仕組み: （なぜそうなるのか。原理・理由。体言止め）
- 数字: （温度・割合・年数・速度など。無ければ「なし」）
- 用語: （専門用語があれば名称と読み。無ければ「なし」）
- 確度: （「教科書・公的機関レベルで確立」か「諸説あり」か。語源・由来・発祥は必ず「諸説あり」）
- 注意: （書くときに外しやすい点。断定を避けるべき箇所。無ければ「なし」）
- 出典: （URLをそのまま1つ転記）

## 2. （以下同じ）

【事実確度】最重要
朝礼で外すと話した人の信用が傷つきます。迷ったら採用しないでください。
- 検索結果に書かれていない事実を足さない。推測で数字を埋めない
- 数字・固有名詞は検索結果からそのまま転記する
- URLは検索結果の「URL:」行から一字一句そのまま転記する（記憶から書かない）
- 裏が取れなかったテーマは、無理に埋めず「確度: 裏取り失敗・不採用推奨」と書く${researchContext}`;
}

// 素材メモが「そのまま投稿できてしまう文章」になっていないかの機械チェック。
// プロンプトで禁止していても生成は非決定的なので、配信前にもう一度見る。
// 引っかかっても配信は止めない（素材が届かないほうが困る）が、警告を添える
export function detectProseLeak(sheet) {
  const warnings = [];
  const desu = (sheet.match(/(です|ます|でした|ました)[。\n]/g) || []).length;
  if (desu > 0) warnings.push(`完成文の語尾が${desu}個含まれています（体言止めのはず）`);
  if (/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(sheet)) warnings.push('絵文字が含まれています');
  if (sheet.includes('朝礼で使うなら')) warnings.push('「朝礼で使うなら」の台本が混ざっています（人が書く部分）');
  return warnings;
}

// GitHub Issueの本文。人が読んで、そのまま執筆に取りかかれる形にする。
// 冒頭の注意書きは形式的なものではなく、守らないと収益化の資格を失う
export function formatIssueBody(dateLabel, sheet, warnings = []) {
  const warnBlock = warnings.length
    ? `\n> ⚠️ 自動チェックの警告: ${warnings.join(' / ')}\n> その部分はそのまま使わず、必ず自分の言葉に置き換えてください。\n`
    : '';
  return `**${dateLabel}｜豆知識の執筆素材**

> 📝 **これは素材であって原稿ではありません**
> 1. 下の事実を材料に、**自分の言葉で**記事を書いてください
> 2. **X公式アプリ／ブラウザから手動で投稿**してください（API・予約投稿は使わない）
> 3. この文面をコピペしたり、少し直しただけで投稿したりしないでください
>
> Original Content Rewards は「created **or** posted using automated means」を対象外としています。
> 生成が自動でも投稿が自動でも失格になるため、この2つは人がやる必要があります。
${warnBlock}
---

${sheet}

---

### 書くときのチェック（詳細は \`cloud-bot/trivia-style.md\`）

- [ ] 3部構成（見出し1行／本文150〜200字／「朝礼で使うなら:」の台本3〜5文・150〜220字）
- [ ] 全体80〜600字
- [ ] Markdown記法（\`**\` \`#\` 行頭 \`-\`）とハッシュタグを使っていない
- [ ] 語源・由来・発祥なら「諸説あります」を本文に入れた
- [ ] 確度の取れない数字・年号・法令名は書いていない（ぼかさず、ネタごと捨てる）
- [ ] 締めが訓示・精神論になっていない

投稿したら、このIssueに投稿URLを返信してからクローズしてください（何を書いたかの記録用）。`;
}

async function main() {
  const now = parseInt(process.env.NOW_MS || '', 10) || Date.now(); // NOW_MSはテスト用フック
  const dateLabel = jstDateLabel(now);
  const covered = loadCoveredTopics();
  console.log(`📋 ${jstDateKey(now)} の豆知識素材を作ります（既出テーマ ${covered.length}件と重複回避）`);

  // 1) テーマ出し（検索なし・事実も書かせない）
  const { text: topicText } = await callAnthropic(buildTopicPrompt(covered), 600, 0);
  const topics = parseTopics(topicText);
  if (!topics.length) throw new Error('テーマ候補を取り出せませんでした');
  topics.forEach((t, i) => console.log(`  ${i + 1}. ${t}`));

  // 2) 裏取り（各テーマをTavilyで検索）
  const { mode, context } = await research(topicPlanFor(topics));
  if (mode !== 'self') {
    // 素材メモは検索結果の転記が命なので、検索が使えない状態では作らない。
    // web_searchツールに退避すると「モデルの記憶で書かれた事実」が混ざり、出典URLも
    // 当てにならなくなる。事実確度が最重要の用途なので、空振りのほうがまだ安全
    console.error('❌ 自前検索（Tavily）が使えないため、素材メモの作成を中止します');
    console.error('   TAVILY_API_KEY を確認してください');
    process.exit(1);
  }

  // 3) 事実の抜き出し
  const { text } = await callAnthropic(buildFactPrompt(topics, dateLabel, context), 2000, 0);
  const sheet = text.trim();
  if (!sheet) throw new Error('素材メモが空です');

  const warnings = detectProseLeak(sheet);
  warnings.forEach(w => console.log(`⚠️ ${w}`));

  console.log(`\n${'='.repeat(40)}\n${safeSlice(sheet, 500)}\n${'='.repeat(40)}\n`);
  return { dateLabel, body: formatIssueBody(dateLabel, sheet, warnings) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { dateLabel, body } = await main();
  const out = process.env.OUTPUT_FILE || 'material-sheet.md';
  fs.writeFileSync(out, body, 'utf8');
  console.log(`💾 ${out} に書き出しました`);
  if (process.env.GITHUB_OUTPUT) {
    fs.appendFileSync(process.env.GITHUB_OUTPUT, `title=${dateLabel}｜豆知識の執筆素材\n`);
  }
}
