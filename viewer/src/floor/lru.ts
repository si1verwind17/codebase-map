// A map that keeps its `max` most recently used entries: a big map's floor plans would otherwise pile up for the session.

/** Least recently used leaves first. `get` and `set` count as a use; `has` does not (a check is no visit). */
export class Lru<K, V> {
  private entries = new Map<K, V>();   // insertion order is use order: the first key is the least recently used

  constructor(readonly max: number) {}

  get(k: K): V | undefined {
    if (!this.entries.has(k)) return undefined;
    const v = this.entries.get(k)!;
    this.entries.delete(k);
    this.entries.set(k, v);
    return v;
  }

  set(k: K, v: V): void {
    this.entries.delete(k);
    this.entries.set(k, v);
    while (this.entries.size > this.max) this.entries.delete(this.entries.keys().next().value!);
  }

  has(k: K): boolean {
    return this.entries.has(k);
  }

  clear(): void {
    this.entries.clear();
  }

  get size(): number {
    return this.entries.size;
  }
}
