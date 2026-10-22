export async function sdkData<T>(request: Promise<{ data: T }>): Promise<T> {
  return (await request).data;
}
