
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Page, Runtime} = client;
  await Page.enable();
  
  await Page.navigate({url: 'https://www.zhipin.com/geek/new/index/'});
  await Page.loadEventFired();
  await new Promise(r => setTimeout(r, 4000));
  
  const result = await Runtime.evaluate({
    expression: `
      JSON.stringify({
        url: window.location.href,
        title: document.title,
        hasUserName: !!document.querySelector('.user-name'),
        userName: document.querySelector('.user-name') ? document.querySelector('.user-name').textContent.trim() : null,
        pageText: document.body.textContent.substring(0, 300),
        isPersonalCenter: document.body.innerHTML.includes('个人中心') || document.body.innerHTML.includes('我的')
      });
    `
  });
  
  console.log(JSON.parse(result.result.value));
  client.close();
})().catch(err => console.error(err));
