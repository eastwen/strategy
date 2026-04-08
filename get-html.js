
const CDP = require('chrome-remote-interface');
const fs = require('fs');

(async function() {
  const client = await CDP({port: 9222});
  const {Runtime} = client;
  
  await new Promise(r => setTimeout(r, 5000));
  
  const result = await Runtime.evaluate({
    expression: "document.documentElement.outerHTML"
  });
  
  const html = result.result.value;
  fs.writeFileSync('/tmp/current-page.html', html);
  console.log('HTML saved to /tmp/current-page.html, size: ' + html.length + ' bytes');
  console.log('\nFirst 300 chars:');
  console.log(html.substring(0, 300));
  client.close();
})().catch(err => console.error(err));
