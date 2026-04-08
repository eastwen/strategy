
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  
  await new Promise(r => setTimeout(r, 2000));
  
  const result = await Runtime.evaluate({
    expression: `
      JSON.stringify({
        myLinks: Array.from(document.querySelectorAll('a')).filter(a => a.textContent.includes('我的')).map(a => ({text: a.textContent.trim(), href: a.href})),
        allLinks: Array.from(document.querySelectorAll('a')).map(a => a.textContent.trim()).filter(t => t.length > 0).slice(0, 20)
      });
    `
  });
  
  console.log(JSON.parse(result.result.value));
  client.close();
})().catch(err => console.error(err));
