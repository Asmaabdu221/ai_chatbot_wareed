const ARABIC_DIGITS = ['٠', '١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩'];

export const formatArabicNumber = (value) => {
  if (value === null || value === undefined) return '';
  return String(value).replace(/\d/g, (digit) => ARABIC_DIGITS[digit]);
};

const isSameDay = (a, b) => {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
};

export const formatArabicDate = (date) => {
  if (!date) return '';
  const target = new Date(date);
  if (Number.isNaN(target.getTime())) return '';

  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);

  if (isSameDay(target, today)) return 'اليوم';
  if (isSameDay(target, yesterday)) return 'أمس';

  return new Intl.DateTimeFormat('ar', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(target);
};

export const formatArabicText = (text) => {
  if (typeof text !== 'string') return text;
  if (!/[\u0600-\u06FF]/.test(text)) return text;

  const urlOrEmail = /(https?:\/\/|www\.)\S+|\S+@\S+\.\S+/i;
  const tokens = text.split(/(\s+)/);

  return tokens
    .map((token) => {
      if (token.trim() === '' || urlOrEmail.test(token)) return token;
      if (!/[\u0600-\u06FF]/.test(token)) return token;
      return token
        .replace(/,/g, '،')
        .replace(/;/g, '؛')
        .replace(/\?/g, '؟');
    })
    .join('');
};
