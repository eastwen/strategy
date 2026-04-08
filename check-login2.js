
const CDP = require('chrome-remote-interface');

async function run() {
  const client = await CDP({ port: 9222 });
  const { Runtime } = client;
  
  await new Promise(resolve => setTimeout(resolve, 5000));
  
  const result = await Runtime.evaluate({
    expression: `
      (function(){
        return {
          title: document.title,
          href: window.location.href,
          hasMy: document.body.textContent.includes('我的'),
          textLength: document.body.textContent.length,
          hasLoginText: document.body.textContent.includes('登录')
        };
      })();
    `
  });
  
  console.log(JSON.stringify(result.result.value, null, 2));
  client.close();
}

run().catch(console.error);
