<script lang="ts">
  // Collections left /movies and /shows when they came to span both; old links still land.
  const { pathname, search, hash } = window.location;
  window.location.replace(
    `${pathname.replace(/^\/(movies|shows)\/collections/, "/collections")}${search}${hash}`,
  );
</script>
