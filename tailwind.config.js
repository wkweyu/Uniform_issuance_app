module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js"
  ],
  theme: {
    extend: {},
  },
  plugins: [],
"scripts": {
  "build-css": "tailwindcss build ./src/input.css -o ./static/css/tailwind.min.css --minify"
}
}