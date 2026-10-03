'use client';

import { useEffect, useState } from 'react';

export type SavedItem = { id: string; kind: string; title: string; href: string };

const KEY = 'ronce.disimpan';

function read(): SavedItem[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function SaveButton({ item }: { item: SavedItem }) {
  const [saved, setSaved] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setSaved(read().some((entry) => entry.id === item.id));
    setReady(true);
  }, [item.id]);

  function toggle() {
    const list = read();
    const next = list.some((entry) => entry.id === item.id)
      ? list.filter((entry) => entry.id !== item.id)
      : [...list, item];
    try {
      window.localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      return;
    }
    setSaved(next.some((entry) => entry.id === item.id));
  }

  return (
    <>
      <button type="button" aria-pressed={saved} onClick={toggle} disabled={!ready}>
        {saved ? 'Tersimpan' : 'Simpan'}
      </button>
      <span className="sr-only" role="status" aria-live="polite">
        {ready ? (saved ? 'Disimpan di perangkat ini' : 'Belum disimpan') : ''}
      </span>
    </>
  );
}

export function SavedList() {
  const [items, setItems] = useState<SavedItem[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setItems(read());
    setReady(true);
  }, []);

  function remove(id: string) {
    const next = read().filter((entry) => entry.id !== id);
    try {
      window.localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      return;
    }
    setItems(next);
  }

  if (!ready) {
    return <p className="muted">Memuat simpanan perangkat…</p>;
  }
  if (items.length === 0) {
    return (
      <p className="muted">
        Belum ada yang disimpan. Simpanan hidup di perangkat ini saja (localStorage), tidak dikirim ke mana pun.
      </p>
    );
  }
  return (
    <ul className="plain">
      {items.map((item) => (
        <li key={item.id}>
          <a href={item.href}>{item.title}</a>
          <div className="small muted">{item.kind}</div>
          <button type="button" className="ghost" onClick={() => remove(item.id)}>
            Hapus dari simpanan
          </button>
        </li>
      ))}
    </ul>
  );
}
