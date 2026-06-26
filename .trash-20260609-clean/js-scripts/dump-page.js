
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  
  await new Promise(r => setTimeout(r, 4000));
  
  const res = await Runtime.evaluate({
    expression: `
      (function(){
        return {
          url: window.location.href,
          title: document.title,
          bodyText: document.body.textContent.substring(0, 500),
          inputs: document.querySelectorAll('input').length,
          buttons: document.querySelectorAll('button').length
        };
      })();
    `
  });
  
  console.log(JSON.stringify(res.result.value, null, 2));
  client.close();
})();
