#!/usr/bin/env node
/**
 * resolve_stream.js — extrai URL reproduzível (prioriza MP4 Mixdrop p/ SS IPTV)
 *
 * Uso: node resolve_stream.js <url_embed|mixdrop|brstream>
 */
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

async function fetchText(url, referer) {
  const headers = { "User-Agent": UA, Accept: "*/*" };
  if (referer) headers["Referer"] = referer;
  const res = await fetch(url, { headers, redirect: "follow" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.text();
}

function unpackPacker(code) {
  const m = code.match(
    /\}\('((?:\\'|[^'])*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'((?:\\'|[^'])*)'\.split\('\|'\)/
  );
  if (!m) return null;
  let payload = m[1].replace(/\\'/g, "'");
  const c = parseInt(m[3], 10);
  const keys = m[4].split("|");
  for (let i = c - 1; i >= 0; i--) {
    if (keys[i]) {
      payload = payload.replace(new RegExp("\\b" + i + "\\b", "g"), keys[i]);
    }
  }
  return payload;
}

function extractMixdropMp4(html) {
  const packers = html.match(
    /eval\(function\(p,a,c,k,e,d\)[\s\S]*?\.split\('\|'\)[\s\S]*?\)\)/g
  );
  if (packers) {
    for (const p of packers) {
      const unpacked = unpackPacker(p);
      if (!unpacked) continue;
      const w = unpacked.match(/MDCore\.wurl\s*=\s*["']([^"']+)["']/);
      if (w) {
        let url = w[1];
        if (url.startsWith("//")) url = "https:" + url;
        if (url.includes(".mp4")) return url;
      }
    }
  }
  const direct = html.match(/MDCore\.wurl\s*=\s*["']([^"']+)["']/);
  if (direct) {
    let url = direct[1];
    if (url.startsWith("//")) url = "https:" + url;
    if (url.includes(".mp4")) return url;
  }
  return null;
}

function buildBrstreamHls(video) {
  const { uid, md5, id, status = "1" } = video;
  if (!uid || !md5 || !id) return null;
  return `https://watch.brstream.cc/m3u8/${uid}/${md5}/master.txt?s=1&id=${id}&cache=${status}`;
}

function parseVideoObject(html) {
  const m = html.match(/var\s+video\s*=\s*(\{[\s\S]*?\});/);
  if (m) {
    try {
      return JSON.parse(m[1]);
    } catch (_) {}
  }
  const uid = html.match(/"uid"\s*:\s*"([^"]+)"/);
  const md5 = html.match(/"md5"\s*:\s*"([^"]+)"/);
  const id = html.match(/"id"\s*:\s*"([^"]+)"/);
  if (uid && md5 && id) return { uid: uid[1], md5: md5[1], id: id[1], status: "1" };
  return null;
}

async function resolveBrstream(watchUrl) {
  const html = await fetchText(watchUrl, "https://embedplay.icu/");
  const video = parseVideoObject(html);
  return video ? buildBrstreamHls(video) : null;
}

async function resolveMixdrop(mixUrl) {
  const html = await fetchText(mixUrl, "https://embedplay.icu/");
  return extractMixdropMp4(html);
}

async function resolveEmbed(embedUrl) {
  const html = await fetchText(embedUrl, "https://comandoplay.tv/");
  const servers = [];
  const re = /playVideo\(['"](https?:\/\/[^'"]+)['"]\)/g;
  let m;
  while ((m = re.exec(html))) {
    if (!servers.includes(m[1])) servers.push(m[1]);
  }
  const mix = servers.find((u) => u.includes("mixdrop"));
  const br = servers.find((u) => u.includes("brstream"));
  // SS IPTV: MP4 primeiro
  if (mix) {
    const mp4 = await resolveMixdrop(mix);
    if (mp4) return mp4;
  }
  if (br) {
    const hls = await resolveBrstream(br);
    if (hls) return hls;
  }
  return servers[0] || null;
}

async function main() {
  const url = process.argv[2];
  if (!url) {
    console.error("Uso: node resolve_stream.js <url>");
    process.exit(1);
  }
  try {
    let result = null;
    if (url.includes("mixdrop")) result = await resolveMixdrop(url);
    else if (url.includes("brstream")) result = await resolveBrstream(url);
    else result = await resolveEmbed(url);
    if (result) {
      process.stdout.write(result + "\n");
      process.exit(0);
    }
    process.exit(2);
  } catch (e) {
    console.error(String(e.message || e));
    process.exit(3);
  }
}

main();
