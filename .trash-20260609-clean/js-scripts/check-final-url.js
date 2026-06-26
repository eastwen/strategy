
const CDP = require('chrome-remote-interface');

(async function() {
  const client = await CDP({port: 9222});
  const {Page} = client;
  await Page.enable();
  
  const history = await Page.getNavigationHistory();
  const current = history.entries[history.currentIndex];
  console.log('Current URL:', current.url);
  console.log('Current title:', current.title);
  
  client.close();
})().catch(err => console.error(err));
