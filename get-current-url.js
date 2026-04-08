
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  
  const result = await Runtime.evaluate({
    expression: `JSON.stringify({url: window.location.href, title: document.title, hasMy: document.body.innerHTML.includes('我的')})`
  });
  
  console.log(JSON.parse(result.result.value));
  client.close();
})();
