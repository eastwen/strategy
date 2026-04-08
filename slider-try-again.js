
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  
  await new Promise(r => setTimeout(r, 2000));
  
  // Click to start
  await Runtime.evaluate({
    expression: `
      (function(){
        const btn = document.querySelector('.geetest_radar_tip');
        if (btn) btn.click();
        return {clicked: !!btn};
      })();
    `
  });
  
  console.log('Clicked start button');
  await new Promise(r => setTimeout(r, 3000));
  
  // Check if it's slider
  const check = await Runtime.evaluate({
    expression: `
      (function(){
        const slider = document.querySelector('#nc_1_n1z');
        return {
          hasSlider: !!slider
        };
      })();
    `
  });
  
  console.log('Check:', check.result.value);
  
  if (check.result.value.hasSlider) {
    await Runtime.evaluate({
      expression: `
        (function(){
          const slider = document.querySelector('#nc_1_n1z');
          const rect = slider.getBoundingClientRect();
          const startX = rect.left;
          const startY = rect.top;
          
          const md = new MouseEvent('mousedown', {
            clientX: startX,
            clientY: startY,
            bubbles: true
          });
          slider.dispatchEvent(md);
          
          let x = startX;
          const iv = setInterval(() => {
            x += 5;
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
              }, 300);
            }
          }, 30);
          
          return {started: true};
        })();
      `
    });
    
    console.log('Slider dragging started');
  }
  
  await new Promise(r => setTimeout(r, 8000));
  
  const result = await Runtime.evaluate({
    expression: `
      (function(){
        return {
          url: window.location.href,
          passed: !window.location.href.includes('verify-slider')
        };
      })();
    `
  });
  
  console.log('Result:', result.result.value);
  
  client.close();
})().catch(err => console.error(err));
