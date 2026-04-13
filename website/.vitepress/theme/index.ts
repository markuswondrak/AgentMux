import DefaultTheme from 'vitepress/theme'
import './custom.css'
import Quickstart from './components/Quickstart.vue'
import Roadmap from './components/Roadmap.vue'
import type { EnhanceAppContext } from 'vitepress'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }: EnhanceAppContext) {
    app.component('Quickstart', Quickstart)
    app.component('Roadmap', Roadmap)
  },
}
