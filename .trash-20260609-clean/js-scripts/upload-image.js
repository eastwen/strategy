
const { callFeishuWikiGet, callFeishuDocUploadImage } = require('/home/admin/.npm-global/lib/node_modules/openclaw/extensions/feishu');

async function main() {
  const token = 'VginwzkfOifirLk75vncFRkcneg';
  console.log('Getting wiki node...');
  const result = await callFeishuWikiGet({ token });
  console.log('Result:', JSON.stringify(result, null, 2));
  
  if (result.obj_token) {
    console.log('Uploading image to doc...');
    const uploadResult = await callFeishuDocUploadImage({
      doc_token: result.obj_token,
      file_path: '/home/admin/.openclaw/workspace/boss-zhipin-full.png'
    });
    console.log('Upload result:', JSON.stringify(uploadResult, null, 2));
  }
}

main().catch(err => {
  console.error('Error:', err);
  process.exit(1);
});
