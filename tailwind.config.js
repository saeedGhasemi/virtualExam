module.exports = {
  content: [
    './templates/**/*.html',
    './apps/**/*.py'
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#2563eb',
          dark: '#1d4ed8'
        },
        page: '#f5f7f2',
        ink: '#14342f',
        muted: '#64716d',
        coral: '#d95d39'
      },
      boxShadow: {
        soft: '0 24px 70px rgba(20, 52, 47, 0.14)',
        subtle: '0 12px 34px rgba(20, 52, 47, 0.08)'
      }
    }
  },
  plugins: []
};
