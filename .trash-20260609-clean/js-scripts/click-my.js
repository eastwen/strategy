
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  
  await new Promise(r => setTimeout(r, 2000));
  
  const result = await Runtime.evaluate({
    expression: `
      (function(){
        const myLink = Array.from(document.querySelectorAll('a')).find(a => a.textContent.trim() === '温晓东');
        if (!myLink) return {found: false};
        myLink.click();
        setTimeout(() => {
          console.log('clicked, waiting for navigate');
        }, 3000);
        return {
          found: true,
          href: myLink.href
        };
      })();
    `
  });
  
  console.log(result.result.value);
  
  await new Promise(r => setTimeout(r, 5000));
  
  const info = await Runtime.evaluate({
    expression: `
      JSON.stringify({
        url: window.location.href,
        title: document.title,
        has投递: document.body.textContent.includes('投递'),
        has简历: document.body.textContent.includes('简历'),
        userName: document.body.textContent.includes('温晓东')
      });
    `
  });
  
  console.log(JSON.parse(info.result.value));
  client.close();
})().catch(err => console.error(err));
