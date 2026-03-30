/* @meta
{
  "name": "twitter/search",
  "description": "搜索推文",
  "domain": "x.com",
  "args": {
    "query": {"required": true, "description": "Search query"},
    "count": {"required": false, "description": "Number of results (default 20, max 50)"},
    "type": {"required": false, "description": "Result type: latest (default) or top"}
  },
  "capabilities": ["network"],
  "readOnly": true,
  "example": "bb-browser site twitter/search \"claude code\""
}
*/

async function(args) {
  if (!args.query) return {error: 'Missing argument: query', hint: 'Provide a search query'};
  const count = Math.min(parseInt(args.count) || 20, 50);
  const product = (args.type === 'top') ? 'Top' : 'Latest';
  const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  const searchUrl = 'https://x.com/search?q=' + encodeURIComponent(args.query) +
    '&src=typed_query&f=' + (product === 'Top' ? 'top' : 'live');
  const searchWin = window.open(searchUrl, '_blank');
  if (!searchWin) return {error: 'Popup blocked', hint: 'Allow popups for x.com in the OpenClaw browser.'};

  try {
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      try {
        const articles = searchWin.document.querySelectorAll('article');
        const bodyText = searchWin.document.body?.innerText || '';
        if (articles.length > 0) break;
        if (bodyText.includes('No results') || bodyText.includes('Try searching for')) break;
      } catch (_) {}
      await wait(500);
    }

    let lastCount = -1;
    let stableRounds = 0;
    for (let i = 0; i < 12; i++) {
      let articleCount = 0;
      try {
        articleCount = searchWin.document.querySelectorAll('article').length;
        searchWin.scrollTo(0, searchWin.document.body.scrollHeight);
      } catch (_) {}
      if (articleCount >= count) break;
      if (articleCount === lastCount) stableRounds += 1;
      else stableRounds = 0;
      if (stableRounds >= 2) break;
      lastCount = articleCount;
      await wait(700);
    }

    const tweets = [];
    const seen = new Set();
    for (const article of Array.from(searchWin.document.querySelectorAll('article'))) {
      const statusLink = Array.from(article.querySelectorAll('a[href*="/status/"]'))
        .map(a => a.href)
        .find(href => /^https:\/\/x\.com\/[^/]+\/status\/\d+$/.test(href));
      if (!statusLink || seen.has(statusLink)) continue;
      seen.add(statusLink);

      const match = statusLink.match(/^https:\/\/x\.com\/([^/]+)\/status\/(\d+)$/);
      const userNameNodes = Array.from(article.querySelectorAll('[data-testid="User-Name"] span'))
        .map(node => node.innerText.trim())
        .filter(Boolean);
      const text = article.querySelector('[data-testid="tweetText"]')?.innerText?.trim() || '';
      tweets.push({
        id: match?.[2],
        author: match?.[1],
        name: userNameNodes.find(value => !value.startsWith('@') && value !== '·'),
        url: statusLink,
        text,
        created_at: article.querySelector('time')?.getAttribute('datetime') || undefined
      });
      if (tweets.length >= count) break;
    }

    return {query: args.query, product, count: tweets.length, tweets};
  } finally {
    try { searchWin.close(); } catch (_) {}
  }
}
