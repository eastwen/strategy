
const CDP = require('chrome-remote-interface');

async function run() {
  const client = await CDP({ port: 9222 });
  const { Runtime } = client;
  
  await new Promise(resolve => setTimeout(resolve, 3000));
  
  const expression = `
    (function() {
      // Find code input
      let codeInput = null;
      const inputs = document.querySelectorAll('input');
      for (let input of inputs) {
        if (input.type === 'number' || 
            (input.placeholder && input.placeholder.includes('验证')) || 
            (input.placeholder && input.placeholder.includes('验证码'))) {
          codeInput = input;
          break;
        }
      }
      
      if (!codeInput) {
        return {foundCode: false};
      }
      
      codeInput.value = '230064';
      codeInput.focus();
      codeInput.dispatchEvent(new Event('input', {bubbles: true}));
      codeInput.dispatchEvent(new Event('change', {bubbles: true}));
      
      // Find login button
      let loginBtn = null;
      const buttons = document.querySelectorAll('button');
      for (let b of buttons) {
        if (b.textContent.includes('登录') || b.textContent.includes('同意')) {
          loginBtn = b;
          break;
        }
      }
      
      return {
        foundCodeInput: !!codeInput,
        filled: codeInput.value === '230064',
        foundLoginBtn: !!loginBtn,
        loginText: loginBtn ? loginBtn.textContent.trim() : null
      };
    })();
  `;
  
  const result = await Runtime.evaluate({expression});
  console.log('填写结果:', JSON.stringify(result, null, 2));
  
  // Click login if we found the button
  if (result.result && result.result.value && result.result.value.foundLoginBtn) {
    const clickExpr = `
      (function(){
        const buttons = document.querySelectorAll('button');
        for (let b of buttons) {
          if (b.textContent.includes('登录') || b.textContent.includes('同意')) {
            b.click();
            return {clicked: true};
          }
        }
        return {clicked: false};
      })();
    `;
    const clickResult = await Runtime.evaluate({expression: clickExpr});
    console.log('点击登录:', JSON.stringify(clickResult, null, 2));
  }
  
  client.close();
}

run().catch(console.error);
