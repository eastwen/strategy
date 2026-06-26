
const CDP = require('chrome-remote-interface');

async function run() {
  const client = await CDP({ port: 9222 });
  const { Page, Runtime, Network } = client;
  await Page.enable();
  
  await new Promise(resolve => setTimeout(resolve, 5000));
  
  // Check current URL and page title
  const {url} = await Page.getNavigationHistory();
  const current = url.entries[url.currentIndex];
  
  const result = await Runtime.evaluate({
    expression: `
      (function(){
        return {
          title: document.title,
          url: window.location.href,
          loggedIn: document.body.textContent.includes('我的') || 
                    document.body.textContent.includes('BOSS直聘') && !document.body.textContent.includes('登录'),
          hasUser: !!document.querySelector('.user-info') || !!document.querySelector('[data-logged-in]')
        };
      })();
    `
  });
  
  console.log('当前页面信息:');
  console.log('  URL:', current.url);
  console.log('  Title:', current.title);
  console.log('  分析:', JSON.stringify(result.result.value, null, 2));
  
  client.close();
}

run().catch(console.error);
