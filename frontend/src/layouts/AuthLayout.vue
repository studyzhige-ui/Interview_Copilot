<template>
  <div class="auth-layout">
    <div class="auth-background">
      <div class="gradient-blob"></div>
      <div class="gradient-blob secondary"></div>
    </div>
    
    <div class="auth-container">
      <router-view v-slot="{ Component }">
        <transition name="slide-up" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </div>
  </div>
</template>

<style scoped>
.auth-layout {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--bg-app);
  position: relative;
  overflow: hidden;
}

.auth-background {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  overflow: hidden;
  z-index: 0;
  opacity: 0.8;
}

.gradient-blob {
  position: absolute;
  width: 60vw;
  height: 60vw;
  border-radius: 50%;
  background: radial-gradient(circle, var(--primary-light) 0%, rgba(255,255,255,0) 70%);
  top: -20vw;
  left: -10vw;
  animation: float 10s ease-in-out infinite alternate;
}

.gradient-blob.secondary {
  background: radial-gradient(circle, #f3e8ff 0%, rgba(255,255,255,0) 70%);
  bottom: -20vw;
  right: -10vw;
  top: auto;
  left: auto;
  animation: float 15s ease-in-out infinite alternate-reverse;
}

@keyframes float {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(5%, 5%) scale(1.05); }
}

.auth-container {
  position: relative;
  z-index: 10;
  width: 100%;
  max-width: 440px;
  padding: 24px;
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: all var(--transition-normal);
}
.slide-up-enter-from {
  opacity: 0;
  transform: translateY(20px);
}
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(-20px);
}
</style>
