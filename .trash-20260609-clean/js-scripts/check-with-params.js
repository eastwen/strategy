
const CDP = require('chrome-remote-interface');

async function run() {
  const client = await CDP({ port: 9222 });
  const { Network, Runtime, Page } = client;
  await Network.enable();
  await Page.enable();
  
  const cookies = await Network.getAllCookies();
  console.log(`Total cookies: ${cookies.cookies.length}`);
  const zhipinCookies = cookies.cookies.filter(c => c.domain.includes('zhipin.com'));
  console.log(`BOSS直聘 cookies 数量: ${zhipinCookies.length}`);
  
  const hasA = zhipinCookies.some(c => c.name === '__a');
  console.log(`有 __a 认证cookie: ${hasA}`);
  
  await new Promise(resolve => setTimeout(resolve, 5000));
  
  const info = await Runtime.evaluate({
    expression: `
      JSON.stringify({
        url: window.location.href,
        title: document.title,
        hasMy: document.body.innerHTML.includes('我的'),
        hasLogout: document.body.innerHTML.includes('退出') || document.body.innerHTML.includes('登出'),
        stillOnLogin: document.body.innerHTML.includes('验证码') && !document.body.innerHTML.includes('我的'),
        links: Array.from(document.querySelectorAll('a')).map(a => a.textContent.trim()).filter(t => t.length > 0).slice(0, 10)
      })
    `
  });
  
  console.log('\n页面信息:');
  console.log(JSON.parse(info.result.value));
  
  client.close();
}

run().catch(console.error);
