/** PUT to a short-lived local or S3 capability URL without leaking account tokens. */
export async function putFileToPresignedUrl(uploadUrl: string, file: File): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
  });
  if (!response.ok) {
    if (response.status === 507) throw new Error('存储空间不足，请释放空间后重试。');
    if (response.status === 413) throw new Error('文件超过存储服务允许的大小。');
    throw new Error(`文件上传失败（HTTP ${response.status}），请重新选择文件后重试。`);
  }
}
