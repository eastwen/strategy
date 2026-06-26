
const CDP = require('chrome-remote-interface');

const cookies = [
{
    "domain": ".zhipin.com",
    "expirationDate": 1808405350.832712,
    "hostOnly": false,
    "httpOnly": false,
    "name": "__a",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": false,
    "storeId": "0",
    "value": "61367804.1760323436.1773761728.1773829528.518.78.11.18",
    "id": 1
},
{
    "domain": ".zhipin.com",
    "hostOnly": false,
    "httpOnly": false,
    "name": "__c",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": true,
    "storeId": "0",
    "value": "1773829528",
    "id": 2
},
{
    "domain": ".zhipin.com",
    "hostOnly": false,
    "httpOnly": false,
    "name": "__g",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": true,
    "storeId": "0",
    "value": "-",
    "id": 3
},
{
    "domain": ".zhipin.com",
    "hostOnly": false,
    "httpOnly": false,
    "name": "__l",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": true,
    "storeId": "0",
    "value": "r=https%3A%2F%2Fwww.baidu.com%2Flink%3Furl%3De1cP9-zdOIYFWRf2NuivZcxqrgedIQ9KxiwnvV-V0pmppj2Y0TJ9h-8wqkSYIpAi%26wd%3D%26eqid%3Dd9c40d6e0044a47f0000000669babb60&l=%2F&s=1",
    "id": 4
},
{
    "domain": ".zhipin.com",
    "hostOnly": false,
    "httpOnly": false,
    "name": "__zp_seo_uuid__",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": true,
    "storeId": "0",
    "value": "d1ae4d45-63d3-4cc6-aadd-44b804fe6f7e",
    "id": 5
},
{
    "domain": ".zhipin.com",
    "expirationDate": 1774075750,
    "hostOnly": false,
    "httpOnly": false,
    "name": "__zp_stoken__",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": false,
    "storeId": "0",
    "value": "fae4gw4rEi8OqwoU8aGBkGcKCwovCgsOAeMOAYMKBT07Dhk14TMK7aMKwZWlQwrZlw4bCucKqw4DCjlTCuFPCvlHDiHTCu8Kvwp7CrsKecsSCVsKmT8Oswr7DssOEw61Sw5%2FCnMKTwrrCok7Ei8KtxItRw61Xw4%2FCrsOMxJbDm8WBxa7CkcO3w4DClTo3w4DEgMS8xYDEvsWDw6PDvMWAxL7Fg8ODxLzFgMS%2Bw6fEg8OUw5DEvsWDxL7EvMWAxL7Fgz9HOj86SUdHwr1gPC9DQUBAw4lDw4hYw4I%2Fw4ZZw4JAw4LCo0IdIBcMDFwWYBgWD2kVZgpcCmESa1ppFGZrXBgWXFoMX2MSMTPDgMKrD8K8EAzCv8O0DcK9w78swrpuDMOQZsKVwpJrOCMqP8KoQEFLw4HFg0BBQzxAQEI6I0Y9Pkg8PUg%2BOjM6wrzCm8OTZMKSwpdkKyNFSD9DQUAsdDo8Qj8%2BOjxEPUQuPEgmLEnCvcSGw4DDjzo8",
    "id": 6
},
{
    "domain": ".zhipin.com",
    "expirationDate": 1774724400.45134,
    "hostOnly": false,
    "httpOnly": false,
    "name": "bst",
    "path": "/",
    "sameSite": "unspecified",
    "secure": true,
    "session": false,
    "storeId": "0",
    "value": "V2RdomFuL8015gXdJuyxoaLS-w7DPSxg~~|RdomFuL8015gXdJuyxoaLS-w7D7WwA~~",
    "id": 7
},
{
    "domain": ".zhipin.com",
    "hostOnly": false,
    "httpOnly": false,
    "name": "Hm_lpvt_194df3105ad7148dcf2b98a91b5e727a",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": true,
    "storeId": "0",
    "value": "1773841130",
    "id": 8
},
{
    "domain": ".zhipin.com",
    "expirationDate": 1805377130,
    "hostOnly": false,
    "httpOnly": false,
    "name": "Hm_lvt_194df3105ad7148dcf2b98a91b5e727a",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": false,
    "storeId": "0",
    "value": "1773460849,1773648737,1773761728,1773829529",
    "id": 9
},
{
    "domain": ".zhipin.com",
    "hostOnly": false,
    "httpOnly": false,
    "name": "HMACCOUNT",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": true,
    "storeId": "0",
    "value": "BF13E639CD513EF3",
    "id": 10
},
{
    "domain": ".zhipin.com",
    "expirationDate": 1805381347.124052,
    "hostOnly": false,
    "httpOnly": false,
    "name": "lastCity",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": false,
    "storeId": "0",
    "value": "101280100",
    "id": 11
},
{
    "domain": ".zhipin.com",
    "expirationDate": 1774724400.685459,
    "hostOnly": false,
    "httpOnly": true,
    "name": "wbg",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": false,
    "storeId": "0",
    "value": "0",
    "id": 12
},
{
    "domain": ".zhipin.com",
    "expirationDate": 1774724400.685407,
    "hostOnly": false,
    "httpOnly": false,
    "name": "wt2",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": false,
    "storeId": "0",
    "value": "Dz9a88GjDybcl8nQbzX-UR8l8JCZ_oRAXXdFCvpw76Imfw_S5xKQjIU0rO51O71jUSsrcg3vZ17rCPT88K6u4yA~~",
    "id": 13
},
{
    "domain": ".zhipin.com",
    "expirationDate": 1774724400.685491,
    "hostOnly": false,
    "httpOnly": false,
    "name": "zp_at",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": false,
    "storeId": "0",
    "value": "H7DphwQOF0H88Oqqr7H0RN8syWuD6rREc-2px359SpU~",
    "id": 14
},
{
    "domain": "www.zhipin.com",
    "expirationDate": 1794883736.089581,
    "hostOnly": true,
    "httpOnly": false,
    "name": "ab_guid",
    "path": "/",
    "sameSite": "unspecified",
    "secure": false,
    "session": false,
    "storeId": "0",
    "value": "d9c83fc1-7fd5-417a-9ea6-212375b07bbd",
    "id": 15
}
];

(async function() {
  const client = await CDP({port: 9222});
  const {Network, Page, Runtime} = client;
  
  await Network.enable();
  await Page.enable();
  
  console.log('Setting', cookies.length, 'cookies...');
  
  for (const cookie of cookies) {
    // CDP format doesn't need id, convert
    const cdpCookie = {
      domain: cookie.domain,
      name: cookie.name,
      value: cookie.value,
      path: cookie.path,
      expires: cookie.expirationDate || (Date.now()/1000 + 86400*7),
      httpOnly: !!cookie.httpOnly,
      secure: !!cookie.secure
    };
    await Network.setCookie(cdpCookie);
  }
  
  console.log('All cookies set');
  
  await new Promise(r => setTimeout(r, 1000));
  
  await Page.navigate({url: 'https://www.zhipin.com/'});
  await Page.loadEventFired();
  
  await new Promise(r => setTimeout(r, 5000));
  
  const result = await Runtime.evaluate({
    expression: `
      JSON.stringify({
        url: window.location.href,
        title: document.title,
        hasMy: document.body.innerHTML.includes('我的'),
        hasLogout: document.body.innerHTML.includes('退出'),
        bodyTextLength: document.body.textContent.length
      });
    `
  });
  
  console.log('Result after setting cookies:');
  console.log(JSON.parse(result.result.value));
  
  client.close();
})().catch(err => console.error(err));
