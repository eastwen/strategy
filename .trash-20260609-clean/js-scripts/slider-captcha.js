
const CDP = require('chrome-remote-interface');

async function run() {
  const client = await CDP({ port: 9222 });
  const { Runtime, DOM } = client;
  await DOM.enable();
  
  await new Promise(resolve => setTimeout(resolve, 5000));
  
  // 找到滑块按钮，尝试拖动从左到右完成验证
  const result = await Runtime.evaluate({
    expression: `
      (function(){
        console.log('Looking for slider...');
        const slider = document.querySelector('.nc_iconfont.btn_slide') || 
                      document.querySelector('#nc_1_n1z') ||
                      document.querySelector('.nc-slider-default .nc-inner');
                      
        if (!slider) {
          return {found: false};
        }
        
        // 尝试模拟拖动滑块从左到右
        const rect = slider.getBoundingClientRect();
        const startX = rect.left + rect.width/2;
        const startY = rect.top + rect.height/2;
        
        // 创建鼠标事件
        const mouseDown = new MouseEvent('mousedown', {
          clientX: startX,
          clientY: startY,
          bubbles: true
        });
        slider.dispatchEvent(mouseDown);
        
        // 拖动到 280px 位置
        for (let x = startX; x < startX + 280; x += 10) {
          const move = new MouseEvent('mousemove', {
            clientX: x,
            clientY: startY,
            bubbles: true
          });
          document.dispatchEvent(move);
        }
        
        const mouseUp = new MouseEvent('mouseup', {
          clientX: startX + 280,
          clientY: startY,
          bubbles: true
        });
        document.dispatchEvent(mouseUp);
        
        return {
          found: true,
          sliderX: startX,
          dragged: true
        };
      })();
    `
  });
  
  console.log('滑块验证结果:', JSON.stringify(result.result.value, null, 2));
  
  await new Promise(resolve => setTimeout(resolve, 3000));
  
  // 现在找手机号输入框
  const fillResult = await Runtime.evaluate({
    expression: `
      (function(){
        let phoneInput = null;
        document.querySelectorAll('input').forEach(i => {
          if (i.type === 'tel' || (i.placeholder && i.placeholder.includes('手机'))) {
            phoneInput = i;
          }
        });
        
        if (!phoneInput) return {foundPhone: false};
        
        phoneInput.value = '15907669055';
        phoneInput.dispatchEvent(new Event('input', {bubbles: true}));
        phoneInput.dispatchEvent(new Event('change', {bubbles: true}));
        
        // 找验证码输入框
        let codeInput = null;
        document.querySelectorAll('input').forEach(i => {
          if (i.type === 'number' || (i.placeholder && i.placeholder.includes('验证'))) {
            codeInput = i;
          }
        });
        
        if (codeInput) {
          codeInput.value = '230064';
          codeInput.dispatchEvent(new Event('input', {bubbles: true}));
          codeInput.dispatchEvent(new Event('change', {bubbles: true}));
        }
        
        // 勾选协议
        document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
          if (!cb.checked) cb.click();
        });
        
        // 点击登录按钮
        let loginBtn = null;
        document.querySelectorAll('button').forEach(b => {
          if (b.textContent.includes('登录')) {
            loginBtn = b;
          }
        });
        
        return {
          foundPhone: !!phoneInput,
          filledPhone: phoneInput.value === '15907669055',
          foundCode: !!codeInput,
          filledCode: codeInput ? codeInput.value === '230064' : false,
          clickedLogin: !!loginBtn,
          loginText: loginBtn ? loginBtn.textContent.trim() : null
        };
      })();
    `
  });
  
  console.log('填写结果:', JSON.stringify(fillResult.result.value, null, 2));
  
  client.close();
}

run().catch(console.error);
