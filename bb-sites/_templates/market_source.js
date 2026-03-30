/* @meta
{
  "name": "example/markets",
  "description": "预测市场或行情榜单模板",
  "domain": "example.com",
  "args": {
    "count": {"required": false, "description": "How many markets to return"}
  },
  "capabilities": ["network"],
  "readOnly": true,
  "example": "bb-browser site example/markets 20"
}
*/

async function(args) {
  const count = Math.min(parseInt(args.count) || 20, 50);
  const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  await wait(1500);

  const markets = Array.from(document.querySelectorAll('[data-role=\"market-row\"]'))
    .slice(0, count)
    .map((node) => ({
      title: node.querySelector('.market-title')?.innerText?.trim() || '',
      url: node.querySelector('a')?.href || '',
      price: node.querySelector('.price')?.innerText?.trim() || '',
      volume: node.querySelector('.volume')?.innerText?.trim() || '',
      probability: node.querySelector('.probability')?.innerText?.trim() || ''
    }))
    .filter((item) => item.title && item.url);

  return {count: markets.length, markets};
}
