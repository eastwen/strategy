
const CDP = require('chrome-remote-interface');
const fs = require('fs');

async function run() {
  const client = await CDP({ port: 9222 });
  const { Runtime } = client;
  
  await new Promise(resolve => setTimeout(resolve, 5000));
  
  const result = await Runtime.evaluate({
    expression: 'document.documentElement.outerHTML.substring(0, 5000)'
  });
  
  const html = result.result.value;
  fs.writeFileSync('/tmp/page.html', html);
  console.log('HTML saved to /tmp/page.html, first 5000 chars');
  console.log('\nPreview:');
  console.log(html.substring(0, 800));
  client.close();
}

run().catch(console.error);
