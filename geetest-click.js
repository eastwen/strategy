
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  
  await new Promise(r => setTimeout(r, 3000));
  
  // Click the start verification button
  const result = await Runtime.evaluate({
    expression: `
      (function(){
        const btn = document.querySelector('.geetest_radar_tip');
        if (!btn) {
          console.log('no button');
          return {clicked: false};
        }
        btn.click();
        console.log('clicked geetest button');
        return {clicked: true};
      })();
    `
  });
  
  console.log('第一步 - 点击验证:', result.result.value);
  
  await new Promise(r => setTimeout(r, 5000));
  
  // Check if we need to slide
  const slideCheck = await Runtime.evaluate({
    expression: `
      (function(){
        const slider = document.querySelector('#nc_1_n1z') || document.querySelector('.geetest_slider');
        return {
          hasSlider: !!slider,
          sliderExists: !!document.querySelector('.geetest_btn')
        };
      })();
    `
  });
  
  console.log('滑块检查:', slideCheck.result.value);
  
  client.close();
})().catch(err => console.error(err));
