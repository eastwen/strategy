
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  await new Promise(r => setTimeout(r, 3000));
  
  const result = await Runtime.evaluate({
    expression: `
      (function() {
        const btn = document.querySelector('.geetest_radar_tip');
        if (!btn) {
          return {step: 'find btn', ok: false};
        }
        btn.click();
        
        setTimeout(() => {
          const slider = document.querySelector('#nc_1_n1z');
          if (!slider) {
            console.log('no slider');
            return;
          }
          const rect = slider.getBoundingClientRect();
          const md = new MouseEvent('mousedown', {
            clientX: rect.left, clientY: rect.top, bubbles: true
          });
          slider.dispatchEvent(md);
          
          let x = rect.left;
          const iv = setInterval(() => {
            x += 8;
            const mv = new MouseEvent('mousemove', {
              clientX: x, clientY: rect.top, bubbles: true
            });
            document.dispatchEvent(mv);
            if (x >= rect.left + 260) {
              clearInterval(iv);
              setTimeout(() => {
                const mu = new MouseEvent('mouseup', {
                  clientX: x, clientY: rect.top, bubbles: true
                });
                document.dispatchEvent(mu);
              }, 300);
            }
          }, 40);
        }, 2000);
        
        return {step: 'started dragging', ok: true};
      })();
    `
  });
  
  console.log('Result:', result.result.value);
  await new Promise(r => setTimeout(r, 10000));
  
  const check = await Runtime.evaluate({
    expression: `
      (function(){
        return {
          url: window.location.href,
          passed: !window.location.href.includes('verify-slider')
        };
      })();
    `
  });
  
  console.log('Check:', check.result.value);
  client.close();
})().catch(err => console.error(err));
