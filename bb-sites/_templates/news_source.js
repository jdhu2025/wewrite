/* @meta
{
  "name": "example/newsflash",
  "description": "新闻快讯模板",
  "domain": "example.com",
  "args": {
    "count": {"required": false, "description": "How many items to return"}
  },
  "capabilities": ["network"],
  "readOnly": true,
  "example": "bb-browser site example/newsflash 20"
}
*/

async function(args) {
  const count = Math.min(parseInt(args.count) || 20, 50);
  const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  await wait(1500);

  const items = Array.from(document.querySelectorAll('[data-role=\"news-item\"]'))
    .slice(0, count)
    .map((node) => ({
      title: node.querySelector('.title')?.innerText?.trim() || '',
      url: node.querySelector('a')?.href || '',
      summary: node.querySelector('.summary')?.innerText?.trim() || '',
      published_at: node.querySelector('time')?.getAttribute('datetime') || undefined
    }))
    .filter((item) => item.title && item.url);

  return {count: items.length, items};
}
