const MAX_SKILL_BYTES = 100 * 1024 * 1024;
const MAX_SKILL_FILES = 20_000;

type GitHubContentItem = {
  download_url: string | null;
  name: string;
  path: string;
  size: number;
  type: "dir" | "file" | "symlink" | "submodule";
};

type DownloadedFile = {
  content: Uint8Array;
  path: string;
};

function sourceParts(sourceUrl: string) {
  let url: URL;
  try {
    url = new URL(sourceUrl);
  } catch {
    throw new Error("在线 Skill 地址无效");
  }
  if (url.protocol !== "https:" || url.username || url.password || url.port) {
    throw new Error("在线 Skill 仅支持 HTTPS GitHub 地址");
  }
  const parts = url.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts.some((part) => part === "." || part === ".." || part.includes("\\"))) {
    throw new Error("在线 Skill 地址包含不安全路径");
  }
  return { url, parts };
}

function rawSkillUrl(sourceUrl: string): { filename: string; url: string } | null {
  const { url, parts } = sourceParts(sourceUrl);
  if (url.hostname === "raw.githubusercontent.com") {
    return { filename: parts.at(-1) || "SKILL.md", url: url.toString() };
  }
  if (
    url.hostname === "github.com"
    && parts.length >= 5
    && ["blob", "raw"].includes(parts[2])
  ) {
    const [owner, repository, , ref, ...path] = parts;
    return {
      filename: path.at(-1) || "SKILL.md",
      url: `https://raw.githubusercontent.com/${encodeURIComponent(owner)}`
        + `/${encodeURIComponent(repository)}/${encodeURIComponent(ref)}`
        + `/${path.map(encodeURIComponent).join("/")}`,
    };
  }
  return null;
}

function githubTree(sourceUrl: string) {
  const { url, parts } = sourceParts(sourceUrl);
  if (url.hostname !== "github.com" || parts.length < 5 || parts[2] !== "tree") {
    throw new Error("内网回退支持 GitHub Skill 目录（/tree/…）或具体 SKILL.md");
  }
  const [owner, repository, , ref, ...path] = parts;
  if (![owner, repository, ref].every((part) => /^[A-Za-z0-9_.-]+$/.test(part))) {
    throw new Error("GitHub Skill 地址中的 owner、repository 或分支格式无效");
  }
  return { owner, repository: repository.replace(/\.git$/, ""), ref, rootPath: path.join("/") };
}

async function checkedResponse(response: Response, message: string) {
  if (response.ok) return response;
  if (response.status === 403 || response.status === 429) {
    throw new Error("GitHub 在线 Skill 下载已触发访问频率限制，请稍后重试");
  }
  if (response.status === 404) {
    throw new Error("GitHub Skill 地址不存在；请检查分支和目录");
  }
  throw new Error(`${message}（HTTP ${response.status}）`);
}

async function listGithubFiles(
  owner: string,
  repository: string,
  ref: string,
  rootPath: string,
): Promise<GitHubContentItem[]> {
  const files: GitHubContentItem[] = [];
  async function visit(path: string, depth: number) {
    if (depth > 16) throw new Error("GitHub Skill 目录层级超过 16 层");
    const encodedPath = path.split("/").map(encodeURIComponent).join("/");
    const endpoint = `https://api.github.com/repos/${encodeURIComponent(owner)}`
      + `/${encodeURIComponent(repository)}/contents/${encodedPath}`
      + `?ref=${encodeURIComponent(ref)}`;
    const response = await checkedResponse(await fetch(endpoint), "读取 GitHub Skill 目录失败");
    const payload = await response.json() as GitHubContentItem | GitHubContentItem[];
    const rows = Array.isArray(payload) ? payload : [payload];
    for (const item of rows) {
      if (item.type === "dir") {
        await visit(item.path, depth + 1);
      } else if (item.type === "file") {
        files.push(item);
        if (files.length > MAX_SKILL_FILES) {
          throw new Error("GitHub Skill 文件数量超过 20000");
        }
      } else {
        throw new Error(`GitHub Skill 包含不支持的 ${item.type}：${item.path}`);
      }
    }
  }
  await visit(rootPath, 0);
  const expectedSkill = `${rootPath.replace(/\/$/, "")}/SKILL.md`.replace(/^\//, "");
  if (!files.some((item) => item.path === expectedSkill)) {
    throw new Error("所选 GitHub 目录根部没有 SKILL.md");
  }
  const declaredBytes = files.reduce((total, item) => total + Math.max(item.size, 0), 0);
  if (declaredBytes > MAX_SKILL_BYTES) {
    throw new Error("GitHub Skill 内容超过 100 MiB");
  }
  return files;
}

async function downloadGithubFiles(
  files: GitHubContentItem[],
  rootPath: string,
): Promise<DownloadedFile[]> {
  const prefix = rootPath.replace(/\/$/, "") + "/";
  const downloaded: DownloadedFile[] = [];
  let totalBytes = 0;
  for (const item of files) {
    if (!item.download_url) throw new Error(`GitHub 文件缺少下载地址：${item.path}`);
    const downloadUrl = new URL(item.download_url);
    if (downloadUrl.protocol !== "https:" || downloadUrl.hostname !== "raw.githubusercontent.com") {
      throw new Error(`GitHub 返回了非受信任下载地址：${item.path}`);
    }
    const response = await checkedResponse(await fetch(downloadUrl), "下载 GitHub Skill 文件失败");
    const content = new Uint8Array(await response.arrayBuffer());
    totalBytes += content.byteLength;
    if (totalBytes > MAX_SKILL_BYTES) throw new Error("GitHub Skill 内容超过 100 MiB");
    downloaded.push({ path: item.path.replace(prefix, ""), content });
  }
  return downloaded;
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let index = 0; index < 256; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) {
      value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : (value >>> 1);
    }
    table[index] = value >>> 0;
  }
  return table;
})();

function crc32(content: Uint8Array) {
  let value = 0xffffffff;
  for (const byte of content) value = CRC_TABLE[(value ^ byte) & 0xff] ^ (value >>> 8);
  return (value ^ 0xffffffff) >>> 0;
}

function joinBytes(parts: Uint8Array[]) {
  const output = new Uint8Array(parts.reduce((total, part) => total + part.byteLength, 0));
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.byteLength;
  }
  return output;
}

export function createStoredZip(files: DownloadedFile[]) {
  const encoder = new TextEncoder();
  const localParts: Uint8Array[] = [];
  const centralParts: Uint8Array[] = [];
  let localOffset = 0;
  for (const file of files) {
    const name = encoder.encode(file.path);
    const checksum = crc32(file.content);
    const local = new Uint8Array(30 + name.byteLength);
    const localView = new DataView(local.buffer);
    localView.setUint32(0, 0x04034b50, true);
    localView.setUint16(4, 20, true);
    localView.setUint16(6, 0x0800, true);
    localView.setUint32(14, checksum, true);
    localView.setUint32(18, file.content.byteLength, true);
    localView.setUint32(22, file.content.byteLength, true);
    localView.setUint16(26, name.byteLength, true);
    local.set(name, 30);
    localParts.push(local, file.content);

    const central = new Uint8Array(46 + name.byteLength);
    const centralView = new DataView(central.buffer);
    centralView.setUint32(0, 0x02014b50, true);
    centralView.setUint16(4, 20, true);
    centralView.setUint16(6, 20, true);
    centralView.setUint16(8, 0x0800, true);
    centralView.setUint32(16, checksum, true);
    centralView.setUint32(20, file.content.byteLength, true);
    centralView.setUint32(24, file.content.byteLength, true);
    centralView.setUint16(28, name.byteLength, true);
    centralView.setUint32(42, localOffset, true);
    central.set(name, 46);
    centralParts.push(central);
    localOffset += local.byteLength + file.content.byteLength;
  }
  const central = joinBytes(centralParts);
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  endView.setUint32(0, 0x06054b50, true);
  endView.setUint16(8, files.length, true);
  endView.setUint16(10, files.length, true);
  endView.setUint32(12, central.byteLength, true);
  endView.setUint32(16, localOffset, true);
  return joinBytes([...localParts, central, end]);
}

export async function downloadOnlineSkillInBrowser(sourceUrl: string): Promise<File> {
  const direct = rawSkillUrl(sourceUrl);
  if (direct) {
    const response = await checkedResponse(await fetch(direct.url), "下载在线 SKILL.md 失败");
    const content = await response.blob();
    if (content.size > MAX_SKILL_BYTES) throw new Error("在线 Skill 内容超过 100 MiB");
    return new File([content], direct.filename, { type: "text/markdown" });
  }
  const source = githubTree(sourceUrl);
  const files = await listGithubFiles(
    source.owner,
    source.repository,
    source.ref,
    source.rootPath,
  );
  const downloaded = await downloadGithubFiles(files, source.rootPath);
  const archive = createStoredZip(downloaded);
  return new File([archive], `${source.rootPath.split("/").at(-1) || "skill"}.zip`, {
    type: "application/zip",
  });
}
