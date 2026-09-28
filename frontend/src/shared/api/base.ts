export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": import.meta.env.VITE_API_KEY ?? "local-demo-key",
      ...init?.headers,
    },
  });
  if (!response.ok)
    throw new Error(`${response.status}: ${await response.text()}`);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function downloadExport() {
  const response = await fetch("/api/analytics/export.xlsx", {
    headers: { "X-API-Key": import.meta.env.VITE_API_KEY ?? "local-demo-key" },
  });
  if (!response.ok)
    throw new Error(`${response.status}: ${await response.text()}`);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "executor-balancer.xlsx";
  link.click();
  URL.revokeObjectURL(url);
}
