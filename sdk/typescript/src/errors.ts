export class DpkError extends Error {
  constructor(message: string, public readonly code = 'InvalidPackage') {
    super(message); this.name = 'DpkError';
  }
}
export function check(value: unknown, message: string): asserts value {
  if (!value) throw new DpkError(message);
}
export async function guarded<T>(action: () => Promise<T>): Promise<T> {
  try { return await action(); }
  catch (error) {
    if (error instanceof DpkError) throw error;
    const e = error as NodeJS.ErrnoException;
    throw new DpkError(e.message ?? String(error), e.code === 'EEXIST' ? 'FileExistsError' : e.code ?? 'InvalidPackage');
  }
}
