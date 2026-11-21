const form = document.getElementById("signup");
const message = document.getElementById("message");

form.addEventListener(
  "invalid",
  () => {
    message.hidden = true;
  },
  true,
);

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const email = form.elements.email.value;
  message.textContent = `Thanks! We sent a link to ${email}.`;
  message.hidden = false;
});
