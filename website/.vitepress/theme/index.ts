import DefaultTheme from 'vitepress/theme'
import './style.css'

import Hero from './components/Hero.vue'
import Features from './components/Features.vue'
import Quickstart from './components/Quickstart.vue'
import Providers from './components/Providers.vue'
import ArchDiagram from './components/ArchDiagram.vue'
import StateMachine from './components/StateMachine.vue'
import DarkCTA from './components/DarkCTA.vue'
import RoadmapHero from './components/RoadmapHero.vue'
import Roadmap from './components/Roadmap.vue'
import RoadmapCTA from './components/RoadmapCTA.vue'
import Step from './components/Step.vue'
import DocCallout from './components/DocCallout.vue'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    const components = {
      Hero,
      Features,
      Quickstart,
      Providers,
      ArchDiagram,
      StateMachine,
      DarkCTA,
      RoadmapHero,
      Roadmap,
      RoadmapCTA,
      Step,
      DocCallout,
    }
    for (const [name, comp] of Object.entries(components)) {
      app.component(name, comp)
    }
  },
}
