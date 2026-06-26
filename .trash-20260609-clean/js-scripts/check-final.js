
const CDP = require('chrome-remote-interface');

async function run() {
  const client = await CDP({ port: 9222 });
  const { Runtime } = client;
  
  await new Promise(resolve => setTimeout(resolve, 8000));
  
  const result = await Runtime.evaluate({
    expression: `
      (function(){
        // 检查是否跳转到主页，检查是否有 "我的" 菜单或者用户信息
        const bodyText = document.body.textContent;
        const hasMy = bodyText.includes('我的');
        const hasJob = bodyText.includes('职位');
        const hasLogin = bodyText.includes('登录');
        const userEl = document.querySelector('.user-name') || document.querySelector('[class*="user"]');
        const userName = userEl ? userEl.textContent.trim() : null;
        
        return {
          url: window.location.href,
          title: document.title,
          hasMyPage: hasMy,
          hasJobs: hasJob,
          stillOnLoginPage: hasLogin && !hasMy,
          userName: userName
        };
      })();
    `
  });
  
  console.log(JSON.stringify(result.result.value, null, 2));
  client.close();
}

run().catch(console.error);
