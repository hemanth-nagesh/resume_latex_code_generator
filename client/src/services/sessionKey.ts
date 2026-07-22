export async function computeSessionKey(jdText: string, sections: string[]): Promise<string> {
  const input = jdText.trim() + '|' + [...sections].sort().join(',');
  const encoder = new TextEncoder();
  const hashBuffer = await crypto.subtle.digest('SHA-256', encoder.encode(input));
  return Array.from(new Uint8Array(hashBuffer))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}
