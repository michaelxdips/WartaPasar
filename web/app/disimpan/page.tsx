import { SavedList } from '@/components/Saved';

export default function DisimpanPage() {
  return (
    <>
      <h1>Disimpan</h1>
      <p className="lede">
        Simpanan hidup di perangkat ini saja (localStorage) dan tidak dikirim ke mana pun. Hapus
        kapan saja dengan tombol pada setiap baris.
      </p>
      <SavedList />
    </>
  );
}
