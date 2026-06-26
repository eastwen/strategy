
const CDP = require('chrome-remote-interface');

async function run() {
  const client = await CDP({ port: 9222 });
  const { Runtime } = client;
  
  await new Promise(resolve => setTimeout(resolve, 3000));
  
  const result = await Runtime.evaluate({
    expression: `
      (function() {
        // Find checkbox for agreement
        let checkbox = null;
        let inputs = document.querySelectorAll('input[type="checkbox"]');
        for (let i of inputs) {
          checkbox = i;
          break;
        }
        
        if (!checkbox) {
          // look by text
          let labels = document.querySelectorAll('label');
          for (let l of labels) {
            if (l.textContent.includes('协议') || l.textContent.includes('同意')) {
              let cb = l.querySelector('input[type="checkbox"]');
              if (cb) checkbox = cb;
              break;
            }
          }
        }
        
        if (checkbox && !checkbox.checked) {
          checkbox.click();
          return {checked: true, found: true};
        } else if (checkbox && checkbox.checked) {
          return {checked: false, found: true, alreadyChecked: true};
        }
        return {found: false};
      })();
    `
  });
  
  console.log('协议勾选结果:', JSON.stringify(result.result.value, null, 2));
  
  // Now click login again
  await Runtime.evaluate({
    expression: `
      (function(){
        const buttons = document.querySelectorAll('button');
        for (let b of buttons) {
          if (b.textContent.includes('登录')) {
            b.click();
            return {clicked: true};
          }
        }
        return {clicked: false};
      })();
    `
  }, (err, res) => {
    console.log('点击登录结果:', err || JSON.stringify(res, null, 2));
  });
  
  client.close();
}

run().catch(console.error);
