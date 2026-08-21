module.exports = {
  content: [
    './templates/**/*.html',
    './apps/**/*.py'
  ],
  theme: {
    fontSize: {
      xs: ['0.6875rem', { lineHeight: '1rem' }],
      sm: ['0.8125rem', { lineHeight: '1.25rem' }],
      base: ['0.875rem', { lineHeight: '1.5rem' }],
      lg: ['1rem', { lineHeight: '1.625rem' }],
      xl: ['1.125rem', { lineHeight: '1.75rem' }],
      '2xl': ['1.375rem', { lineHeight: '2rem' }],
      '3xl': ['1.75rem', { lineHeight: '2.25rem' }],
      '4xl': ['2.125rem', { lineHeight: '2.5rem' }],
      '5xl': ['2.625rem', { lineHeight: '1.1' }],
      '6xl': ['3rem', { lineHeight: '1.08' }],
      '7xl': ['3.5rem', { lineHeight: '1.05' }],
      '8xl': ['4.25rem', { lineHeight: '1' }],
      '9xl': ['5rem', { lineHeight: '1' }],
    },
    extend: {
      colors: {
        brand: {
          DEFAULT: '#2563eb',
          dark: '#1d4ed8'
        },
        page: '#f8fafc',
        ink: '#10205f',
        muted: '#64716d',
        coral: '#d95d39',
        lavender: '#f2e2fb'
      },
      boxShadow: {
        soft: '0 24px 70px rgba(20, 52, 47, 0.14)',
        subtle: '0 12px 34px rgba(20, 52, 47, 0.08)'
      }
    }
  },
  plugins: []
};
