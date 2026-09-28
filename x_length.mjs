import twitterText from 'twitter-text';

const text = await new Promise((resolve, reject) => {
  let input = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { input += chunk; });
  process.stdin.on('end', () => resolve(input));
  process.stdin.on('error', reject);
});
const result = twitterText.parseTweet(text);
process.stdout.write(JSON.stringify({ weighted_length: result.weightedLength, valid: result.valid }));
