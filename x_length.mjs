import twitterText from 'twitter-text';
import {Readable} from 'stream';

// Read all stdin as binary buffer, then decode to UTF-8 string
const chunks = [];
const readable = Readable.from(process.stdin);

readable.on('data', (chunk) => {
  chunks.push(chunk);
});

readable.on('end', () => {
  const buffer = Buffer.concat(chunks);
  const text = buffer.toString('utf8');

  try {
    const result = twitterText.parseTweet(text);
    process.stdout.write(JSON.stringify({
      weighted_length: result.weightedLength,
      valid: result.valid
    }));
    process.exit(0);
  } catch (err) {
    process.stderr.write(JSON.stringify({ error: err.message }));
    process.exit(1);
  }
});

readable.on('error', (err) => {
  process.stderr.write(JSON.stringify({ error: err.message }));
  process.exit(1);
});
