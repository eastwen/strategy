
const CDP = require('chrome-remote-interface');

async function run() {
  const client = await CDP({ port: 9222 });
  const { Network, Runtime } = client;
  await Network.enable();
  
  const cookies = await Network.getAllCookies();
  console.log('Number of cookies:', cookies.cookies.length);
  
  // Find login related cookies
  const bossCookies = cookies.cookies.filter(c => c.domain.includes('zhipin.com'));
  console.log('BOSS zhipin cookies:', bossCookies.length);
  const hasAuthCookie = bossCookies.some(c => c.name.includes('a') || c.name.includes('auth') || c.name.includes('token'));
  console.log('Has auth cookie:', hasAuthCookie);
  
  // Check if we're on the main page
  await new Promise(resolve => setTimeout(resolve, 3000));
  const result = await Runtime.evaluate({
    expression: `
      JSON.stringify({
        href: window.location.href,
        title: document.title,
        hasMyNavbar: !!document.querySelector('a[href*="my"]') || document.documentElement.innerHTML.includes('我的'),
        bodyLength: document.body.textContent.length
      })
    `
  });
  
  console.log('Page info:', JSON.parse(result.result.value));
  
  client.close();
}

run().catch(console.error);
