
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  
  await new Promise(r => setTimeout(r, 2000));
  
  // 九宫格坐标估算 (每个格子大概 100px x 100px)
  // 第一行: y ~ 50,  1: x~40,  2:x~145,  3:x~250
  // 第二行: y ~ 150, 1: x~40,  2:x~145,  3:x~250
  // 第三行: y ~ 250, 1: x~40,  2:x~145,  3:x~250
  
  // 用户说: 第一行第一个(1), 二行第三个(2), 第三行第一(3), 第三行第二(4)
  const points = [
    {x: 40,  y: 50},   // 1 - 第一行第一个
    {x: 250, y: 150},  // 2 - 第二行第三个
    {x: 40,  y: 250},  // 3 - 第三行第一个
    {x: 145, y: 250}   // 4 - 第三行第二个
  ];
  
  console.log('Clicking points:', points);
  
  for (const p of points) {
    await Runtime.evaluate({
      expression: `
        (function(){
          const el = document.querySelector('.geetest_fullpage_click_box');
          if (!el) return false;
          const rect = el.getBoundingClientRect();
          const x = rect.left + ${p.x};
          const y = rect.top + ${p.y};
          const down = new MouseEvent('mousedown', {clientX: x, clientY: y, bubbles: true});
          document.dispatchEvent(down);
          setTimeout(() => {
            const up = new MouseEvent('mouseup', {clientX: x, clientY: y, bubbles: true});
            document.dispatchEvent(up);
          }, 100);
          return true;
        })();
      `
    });
    await new Promise(r => setTimeout(r, 500));
  }
  
  // Click confirm
  await new Promise(r => setTimeout(r, 500));
  const confirmResult = await Runtime.evaluate({
    expression: `
      (function(){
        const confirmBtn = document.querySelector('.geetest_commit');
        if (!confirmBtn) return false;
        confirmBtn.click();
        return true;
      })();
    `
  });
  
  console.log('Clicked confirm:', confirmResult.result.value);
  
  await new Promise(r => setTimeout(r, 3000));
  
  // Check result
  const checkResult = await Runtime.evaluate({
    expression: `
      (function(){
        const url = window.location.href;
        const hasVerify = url.includes('verify-slider');
        return {
          url: url,
          stillOnVerify: hasVerify,
          bodyLength: document.body.textContent.length
        };
      })();
    `
  });
  
  console.log('Result after confirm:', checkResult.result.value);
  
  client.close();
})().catch(err => console.error(err));
