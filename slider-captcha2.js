
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  
  await new Promise(r => setTimeout(r, 5000));
  
  // Find slider and drag
  const sliderRes = await Runtime.evaluate({
    expression: `\n(function() {\n  const slider = document.querySelector('#nc_1_n1z');\n  if (!slider) {\n    return {found: false};\n  }\n  console.log('Found slider');\n  const rect = slider.getBoundingClientRect();\n  const down = new MouseEvent('mousedown', {clientX: rect.left, clientY: rect.top, bubbles: true});\n  slider.dispatchEvent(down);\n  \n  let x = rect.left;\n  const interval = setInterval(() => {\n    x += 10;\n    const move = new MouseEvent('mousemove', {clientX: x, clientY: rect.top, bubbles: true});\n    document.dispatchEvent(move);\n    if (x >= rect.left + 260) {\n      clearInterval(interval);\n      setTimeout(() => {\n        const up = new MouseEvent('mouseup', {clientX: x, clientY: rect.top, bubbles: true});\n        document.dispatchEvent(up);\n      }, 300);\n    }\n  }, 50);\n  \n  return {found: true, startX: rect.left};\n})();\n`
  });
  
  console.log('Slider:', sliderRes.result.value);
  
  await new Promise(r => setTimeout(r, 3000));
  
  // Fill phone and code
  const fillRes = await Runtime.evaluate({
    expression: `\n(function() {\n  // Fill phone\n  let phoneIn = null;\n  document.querySelectorAll('input').forEach(inp => {\n    if (inp.type === 'tel' || (inp.placeholder && inp.placeholder.indexOf('手机') >= 0)) {\n      phoneIn = inp;\n    }\n  });\n  if (!phoneIn) return {phone: false};\n  phoneIn.value = '15907669055';\n  phoneIn.dispatchEvent(new Event('input', {bubbles: true}));\n  \n  // Fill code\n  let codeIn = null;\n  document.querySelectorAll('input').forEach(inp => {\n    if (inp.type === 'number' || (inp.placeholder && inp.placeholder.indexOf('验证码') >= 0)) {\n      codeIn = inp;\n    }\n  });\n  if (!codeIn) return {phone: true, code: false};\n  codeIn.value = '230064';\n  codeIn.dispatchEvent(new Event('input', {bubbles: true}));\n  \n  // Check agreement\n  document.querySelectorAll('input[type=\"checkbox\"]').forEach(cb => {\n    if (!cb.checked) cb.click();\n  });\n  \n  // Click login\n  let loginBtn = null;\n  document.querySelectorAll('button').forEach(btn => {\n    if (btn.textContent.indexOf('登录') >= 0) loginBtn = btn;\n  });\n  if (loginBtn) loginBtn.click();\n  \n  return {\n    phone: true,\n    code: true,\n    clickedLogin: !!loginBtn\n  };\n})();\n`
  });
  
  console.log('Fill:', fillRes.result.value);
  
  client.close();
})().catch(err => console.error(err));
