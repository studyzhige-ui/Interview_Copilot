export const money = (micros: string) => {
  if (!/^\d+$/.test(micros)) return '无效金额';
  const value = BigInt(micros);
  const integer = (value / 1_000_000n).toLocaleString();
  const fraction = (value % 1_000_000n).toString().padStart(6, '0').replace(/0+$/, '');
  return fraction ? `${integer}.${fraction}` : integer;
};
