
const CDP = require('chrome-remote-interface');

async function run() {
  const client = await CDP({ port: 9222 });
  const { Runtime } = client;
  
  await new Promise(resolve => setTimeout(resolve, 10000));
  
  const expression = `
    (function() {
      console.log('Looking for phone input...');
      let phoneInput = null;
      const inputs = document.querySelectorAll('input');
      for (let input of inputs) {
        if (input.type === 'tel' || 
            (input.placeholder && input.placeholder.includes('手机')) || 
            (input.placeholder && input.placeholder.includes('号码'))) {
          phoneInput = input;
          break;
        }
      }
      
      if (!phoneInput) {
        return {found: false};
      }
      
      phoneInput.value = '15907669055';
      phoneInput.focus();
      phoneInput.dispatchEvent(new Event('input', {bubbles: true}));
      phoneInput.dispatchEvent(new Event('change', {bubbles: true}));
      
      let btn = null;
      const buttons = document.querySelectorAll('button');
      for (let b of buttons) {
        if (b.textContent.includes('获取') || b.textContent.includes('验证码')) {
          btn = b;
          break;
        }
      }
      
      return {
        foundInput: !!phoneInput,
        filled: phoneInput.value === '15907669055',
        foundButton: !!btn,
        buttonText: btn ? btn.textContent.trim() : null
      };
    })();
  `;
  
  const result = await Runtime.evaluate({expression});
  console.log('执行结果:', JSON.stringify(result, null, 2));
  client.close();
}

run().catch(console.error);
