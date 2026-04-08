
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  
  await new Promise(r => setTimeout(r, 5000));
  
  // Fill phone
  await Runtime.evaluate({
    expression: `
      (function(){
        let phoneInput = null;
        document.querySelectorAll('input').forEach(i => {
          if (i.type === 'tel' || (i.placeholder && i.placeholder.includes('手机'))) {
            phoneInput = i;
          }
        });
        
        if (!phoneInput) return {phone: false};
        phoneInput.value = '15907669055';
        phoneInput.dispatchEvent(new Event('input', {bubbles: true}));
        phoneInput.dispatchEvent(new Event('change', {bubbles: true}));
        
        // Fill code
        let codeInput = null;
        document.querySelectorAll('input').forEach(i => {
          if (i.type === 'number' || (i.placeholder && i.placeholder.includes('验证'))) {
            codeInput = i;
          }
        });
        
        if (!codeInput) return {phone: true, code: false};
        codeInput.value = '230064';
        codeInput.dispatchEvent(new Event('input', {bubbles: true}));
        codeInput.dispatchEvent(new Event('change', {bubbles: true}));
        
        // Check agreement
        document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
          if (!cb.checked) cb.click();
        });
        
        // Click login
        let loginBtn = null;
        document.querySelectorAll('button').forEach(b => {
          if (b.textContent.includes('登录')) {
            loginBtn = b;
          }
        });
        
        if (loginBtn) {
          loginBtn.click();
          console.log('login clicked');
        }
        
        return {
          phone: true,
          code: true,
          clickedLogin: !!loginBtn
        };
      })();
    `
  }, (err, res) => {
    console.log('Login fill result:', err || res.result.value);
  });
  
  await new Promise(r => setTimeout(r, 5000));
  
  const result = await Runtime.evaluate({
    expression: `
      (function(){
        return {
          url: window.location.href,
          title: document.title,
          isLoginPage: window.location.href.includes('/web/user/') && !window.location.href.includes('verify'),
          hasMy: document.body.innerHTML.includes('我的'),
          hasLogout: document.body.innerHTML.includes('退出')
        };
      })();
    `
  });
  
  console.log('Final status:', result.result.value);
  
  client.close();
})().catch(err => console.error(err));
