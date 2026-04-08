
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  
  await new Promise(r => setTimeout(r, 4000));
  
  await Runtime.evaluate({
    expression: `
      setTimeout(function() {
        const slider = document.querySelector('.geetest_radar_tip');
        if (slider) slider.click();
      }, 1000);
      
      setTimeout(function() {
        const dragBtn = document.querySelector('#nc_1_n1z');
        if (!dragBtn) {
          console.log('no drag button');
          return;
        }
        console.log('found drag button');
        const rect = dragBtn.getBoundingClientRect();
        const startX = rect.left;
        const startY = rect.top;
        
        // Mouse down
        const md = new MouseEvent('mousedown', {
          clientX: startX,
          clientY: startY,
          bubbles: true
        });
        dragBtn.dispatchEvent(md);
        
        // Drag to end
        let x = startX;
        const iv = setInterval(() => {
          x += 8;
          const mv = new MouseEvent('mousemove', {
            clientX: x,
            clientY: startY,
            bubbles: true
          });
          document.dispatchEvent(mv);
          
          if (x >= startX + 260) {
            clearInterval(iv);
            setTimeout(() => {
              const mu = new MouseEvent('mouseup', {
                clientX: x,
                clientY: startY,
                bubbles: true
              });
              document.dispatchEvent(mu);
              console.log('drag finished');
            }, 300);
          }
        }, 40);
      }, 1500);
      
      return {started: true};
    `
  });
  
  console.log('Drag initiated, waiting for completion...');
  await new Promise(r => setTimeout(r, 8000));
  
  // Check if passed
  const passed = await Runtime.evaluate({
    expression: `
      (function(){
        const hasSuccess = !!document.querySelector('.geetest_success');
        const url = window.location.href;
        return {
          passed: hasSuccess || !url.includes('verify-slider'),
          currentUrl: url
        };
      })();
    `
  });
  
  console.log('验证结果:', passed.result.value);
  
  client.close();
})().catch(err => console.error(err));
