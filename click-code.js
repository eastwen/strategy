
const CDP = require('chrome-remote-interface');

async function run() {
  const client = await CDP({ port: 9222 });
  const { Runtime } = client;
  
  await new Promise(resolve => setTimeout(resolve, 3000));
  
  const expression = `
    (function() {
      // Find get code button
      let btn = null;
      const buttons = document.querySelectorAll('button');
      for (let b of buttons) {
        if (b.textContent.includes('获取') || b.textContent.includes('验证码') || b.textContent.includes('重新')) {
          btn = b;
          break;
        }
      }
      
      if (!btn) {
        return {found: false};
      }
      
      btn.click();
      return {
        clicked: true,
        buttonText: btn.textContent.trim()
      };
    })();
  `;
  
  const result = await Runtime.evaluate({expression});
  console.log('点击结果:', JSON.stringify(result, null, 2));
  client.close();
}

run().catch(console.error);
